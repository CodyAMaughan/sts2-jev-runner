using System.Diagnostics;
using Environment=System.Environment;
using MegaCrit.Sts2.Core.Multiplayer.Game.PeerInput;
using System.Text.Json;
using System.Text.Json.Nodes;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Assets;
namespace OvernightHarness;

// Recorded-position playback. Navigation loads the model graph from one file;
// it never submits recorded gameplay actions or reconstructs earlier rooms.
[HarmonyPatch(typeof(AutoSlayer),"RunAsync")]
static class SnapshotPlayback
{
    public static bool Enabled=>!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_PLAYBACK"));
    static readonly JsonSerializerOptions Json=new(){IncludeFields=true};
    static string directory="",controls="";static int current,total;static bool playing;static double delay=1;
    [HarmonyPriority(Priority.First)]
    static bool Prefix(ref Task __result) {if(!Enabled)return true;__result=Run();return false;}
    static void Status(string mode) {
        Directory.CreateDirectory(controls);string path=Path.Combine(controls,"status.json");
        File.WriteAllText(path+".tmp",JsonSerializer.Serialize(new{index=current,total,mode,seconds=delay,mechanism="direct_snapshot",reconstruction_index=(int?)null}));File.Move(path+".tmp",path,true);
    }
    static string Comparable(string json) {
        var obj=JsonNode.Parse(json)!.AsObject();
        foreach(string key in new[]{"nextChoiceIds","nextRewardIds","lastExecutedHookId","lastExecutedActionId"})obj.Remove(key);
        return obj.ToJsonString();
    }
    static async Task Load(int index) {
        var watch=Stopwatch.StartNew();
        var envelope=DecisionSnapshots.Read(Path.Combine(directory,(index+1)+".json.gz"));
        var run=(RunState)envelope.Graph.Restore();
        var manager=RunManager.Instance;
        bool initialize=manager.DebugOnlyGetState()==null;
        AccessTools.Property(typeof(RunManager),"State").SetValue(manager,run);
        if(initialize) {
            var net=new NetSingleplayerGameService();
            AccessTools.Method(typeof(RunManager),"InitializeShared").Invoke(manager,new object?[]{net,new PeerInputSynchronizer(net),false,null,0L,0L,0L,0});
            AccessTools.Method(typeof(RunManager),"InitializeRunLobby").Invoke(manager,new object[]{net,run});
            MegaCrit.Sts2.Core.Context.LocalContext.NetId=net.NetId;
        }
        var combat=run.Players[0].Creature.CombatState;
        AccessTools.Field(typeof(CombatManager),"_state").SetValue(CombatManager.Instance,combat);
        AccessTools.Property(typeof(CombatManager),"IsInProgress").SetValue(CombatManager.Instance,envelope.CombatInProgress);
        string actual=JsonSerializer.Serialize(NetFullCombatState.FromRun(run,null),Json);
        if(Comparable(actual)!=Comparable(envelope.NativeState))throw new InvalidDataException("Loaded snapshot differs from captured native state at "+envelope.DecisionId);
        if(Environment.GetEnvironmentVariable("DEALMAKER_HEADED")=="1" || Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_VALIDATE_SCENES")=="1") {
            await Present(run,envelope);
            string afterScene=JsonSerializer.Serialize(NetFullCombatState.FromRun(run,null),Json);
            if(Comparable(afterScene)!=Comparable(envelope.NativeState))throw new InvalidDataException("Scene presentation changed recorded model state");
        }
        DecisionBridge.SetPlaybackObservation(envelope.Observation.GetRawText());
        current=index;
        Harness.Log("snapshot_loaded",new{index,decision_id=envelope.DecisionId,kind=envelope.Kind,milliseconds=watch.Elapsed.TotalMilliseconds,earlier_actions_executed=0,native_state_verified=true});
    }
    static async Task Present(RunState run,DecisionSnapshots.Envelope envelope) {
        await PreloadManager.LoadRunAssets(run.Players.Select(p=>p.Character));
        await PreloadManager.LoadActAssets(run.Act);
        NGame.Instance!.RootSceneContainer.SetCurrentScene(NRun.Create(run));
        if(run.CurrentRoom is CombatRoom combatRoom && combatRoom.CombatState!=null && envelope.Kind is "combat" or "card_selection") {
            await PreloadManager.LoadRoomCombatAssets(combatRoom.Encounter,run);
            var scene=NCombatRoom.Create(combatRoom,CombatRoomMode.ActiveCombat)!;
            // SetCurrentRoom publishes an active-screen event immediately;
            // suppress its combat Enable callback until Ui.Activate has bound state.
            AccessTools.Property(typeof(CombatManager),"IsInProgress").SetValue(CombatManager.Instance,false);
            try {NRun.Instance!.SetCurrentRoom(scene);scene.SetUpBackground(run);scene.Ui.Activate(combatRoom.CombatState);}
            finally {AccessTools.Property(typeof(CombatManager),"IsInProgress").SetValue(CombatManager.Instance,envelope.CombatInProgress);}
            foreach(var card in run.Players[0].PlayerCombatState?.Hand.Cards ?? Enumerable.Empty<MegaCrit.Sts2.Core.Models.CardModel>()) {
                var node=NCard.Create(card)!;scene.Ui.Hand.Add(node);
                if(scene.Ui.Hand.GetCard(card)==null)throw new InvalidDataException("Snapshot card failed to bind into hand");
            }
            foreach(var creature in combatRoom.CombatState.Creatures)if(scene.GetCreatureNode(creature)==null)throw new InvalidDataException("Snapshot creature failed to bind into combat room");
            // Recorded playback controls own navigation; avoid accidental live actions.
            var shield=new Control{MouseFilter=Control.MouseFilterEnum.Stop};shield.SetAnchorsAndOffsetsPreset(Control.LayoutPreset.FullRect);scene.AddChild(shield);
            Harness.Log("snapshot_scene_verified",new{decision_id=envelope.DecisionId,kind=envelope.Kind,hand=run.Players[0].PlayerCombatState?.Hand.Cards.Count,creatures=combatRoom.CombatState.Creatures.Count});
        } else {
            // Other decision types retain their complete native state. Render
            // the recorded choice text without executing event/shop callbacks.
            var panel=new PanelContainer{Position=new Vector2(180,160),Size=new Vector2(1400,700)};
            var text=new RichTextLabel{BbcodeEnabled=false,Text=Describe(envelope),ScrollActive=true};panel.AddChild(text);NRun.Instance!.AddChild(panel);
        }
    }
    static string Describe(DecisionSnapshots.Envelope envelope) {
        var observation=envelope.Observation;var lines=new List<string>{envelope.Kind.Replace('_',' ').ToUpperInvariant(),"Recorded decision "+envelope.DecisionId,""};
        var state=observation.GetProperty("state");
        foreach(string key in new[]{"prompt","text"})if(state.TryGetProperty(key,out var text) && text.ValueKind==JsonValueKind.String)lines.Add(text.GetString()!);
        foreach(var action in observation.GetProperty("actions").EnumerateArray()) {
            var option=action.GetProperty("option");string label="";
            if(option.TryGetProperty("card",out var card) && card.TryGetProperty("name",out var name))label=name.GetString()!;
            else if(option.TryGetProperty("text",out var text) && text.ValueKind==JsonValueKind.String)label=text.GetString()!;
            else if(option.TryGetProperty("action",out var verb))label=verb.GetString()!.Replace('_',' ');
            lines.Add("• "+label);
        }
        return string.Join("\n",lines);
    }
    static async Task Run() {
        directory=Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_PLAYBACK")!;
        controls=Environment.GetEnvironmentVariable("DEALMAKER_REPLAY_CONTROLS")??Path.Combine(directory,"playback");
        total=Directory.GetFiles(directory,"*.json.gz").Length;
        current=Math.Clamp(int.Parse(Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_INDEX")??"0"),0,total-1);
        try {
            await Load(current);Status("Paused");
            if(Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_VERIFY")=="1") {
                var indices=new[]{total-1,0,total/2,Math.Max(0,total/2-1),Math.Min(total-1,156),Math.Min(total-1,157),Math.Min(total-1,156),0};
                foreach(int index in indices)await Load(index);
                Harness.Log("snapshot_navigation_verified",new{loads=indices.Length+1,total,earlier_actions_executed=0,mode="headless"});Status("Finished");return;
            }
            string? last=null;var timer=Stopwatch.StartNew();
            while(true) {
                string commandPath=Path.Combine(controls,"command.json");
                if(File.Exists(commandPath)) {
                    using var doc=JsonDocument.Parse(File.ReadAllText(commandPath));var c=doc.RootElement;string? nonce=c.GetProperty("nonce").GetString();
                    if(nonce!=last) {
                        last=nonce;string action=c.GetProperty("action").GetString()!;
                        if(action=="stop")break;
                        if(action=="play"){playing=true;timer.Restart();}
                        if(action=="pause")playing=false;
                        if(action=="rate")delay=Math.Clamp(c.GetProperty("seconds").GetDouble(),0,60);
                        if(action is "back" or "step" or "seek") {
                            playing=false;int target=action=="back"?current-1:action=="step"?current+1:c.GetProperty("index").GetInt32();
                            await Load(Math.Clamp(target,0,total-1));timer.Restart();
                        }
                    }
                }
                if(playing && timer.Elapsed.TotalSeconds>=delay){if(current+1<total)await Load(current+1);else playing=false;timer.Restart();}
                Status(playing?"Playing":"Paused");await Task.Delay(50);
            }
            Harness.Log("snapshot_playback_stopped",new{index=current,earlier_actions_executed=0});Status("Stopped");
        } catch(Exception e) {Harness.Log("snapshot_playback_failed",new{error=e.ToString()});Status("Failed");}
        finally {NGame.Instance!.GetTree().Quit(0);}
    }
}
