using System.IO.Compression;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Assets;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer.Game.PeerInput;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Rooms;
namespace OvernightHarness;
public static class DecisionSnapshots
{
    public static bool CaptureEnabled=>Environment.GetEnvironmentVariable("DEALMAKER_SNAPSHOT_CAPTURE")=="1";
    static readonly JsonSerializerOptions Json=new(){IncludeFields=true};
    public sealed class Envelope {
        public int Schema {get;set;}=1;
        public string DecisionId {get;set;}="";
        public bool CombatInProgress {get;set;}
        public string Kind {get;set;}="";
        public string GameAssemblyHash {get;set;}="";
        public string NativeState {get;set;}="";
        public JsonElement Observation {get;set;}
        public DecisionSnapshotGraph Graph {get;set;}=new();
    }
    public static Envelope Read(string file) {
        using var stream=File.OpenRead(file);using var zip=new GZipStream(stream,CompressionMode.Decompress);
        var envelope=JsonSerializer.Deserialize<Envelope>(zip,Json)!;
        if(envelope.Schema!=1)throw new InvalidDataException("Unsupported snapshot format");
        string hash=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(RunState).Assembly.Location)));
        if(hash!=envelope.GameAssemblyHash)throw new InvalidDataException("Snapshot game assembly differs");
        return envelope;
    }
    // Shared by SnapshotPlayback (read-only viewing) and SnapshotResume (hands
    // control back to the live decision loop). Restores the captured RunState and
    // installs it as the live RunManager/CombatManager state via the same
    // reflection path, then verifies the injected state matches what was captured
    // — this is the same round-trip check DecisionSnapshotGraph.Capture already
    // performs at capture time, re-run here against the actual live singletons
    // rather than a throwaway comparison object.
    public static RunState Inject(Envelope envelope) {
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
        // A normal combat start registers every card's network ID as a side
        // effect (NetCombatCardDb.StartCombat, called from the real combat-start
        // path we never ran). Without it, PlayCardAction throws the moment a
        // resumed run tries to actually play a restored card: "could not be
        // found in combat ID database." Read-only playback never hits this
        // (it never submits an action), but any live-interaction consumer needs
        // it. StartCombat resets and re-registers, so it's safe to call again.
        if(envelope.CombatInProgress)NetCombatCardDb.Instance.StartCombat(run.Players);
        // Same pattern, a second subsystem: the game's own action-replay/checksum
        // writer (CombatReplayWriter) subscribes to every enqueued action and
        // requires RecordInitialState() first — normally called from the same
        // real combat/room-entry code we bypass. Without it, actions are enqueued
        // and accepted by our bridge, but the game's internal handler throws
        // ("RecordInitialState must be called first"), catches its own exception,
        // and the action never actually applies — no crash, no error surfaced to
        // us, just a state that silently never changes.
        if(manager.CombatReplayWriter.IsEnabled)manager.CombatReplayWriter.RecordInitialState(manager.ToSave(null));
        // Third instance of the same pattern: ActionQueueSynchronizer tracks its
        // own CombatState (NotInCombat/PlayPhase/NotPlayPhase/...), normally
        // driven by SetCombatState() calls as combat/turns begin and end. It
        // defaults to NotInCombat/NotPlayPhase — and RequestEnqueue silently
        // *defers* any CombatPlayPhaseOnly action (i.e. every card play) into a
        // holding queue whenever CombatState isn't PlayPhase, with no error. A
        // snapshot is only ever captured at a decision point (a live choice was
        // offered), and play_card is only ever offered during the player's own
        // turn, so PlayPhase is always the correct state for an injected combat.
        if(envelope.CombatInProgress)manager.ActionQueueSynchronizer.SetCombatState(ActionSynchronizerCombatState.PlayPhase);
        string actual=JsonSerializer.Serialize(NetFullCombatState.FromRun(run,null),Json);
        if(Comparable(actual)!=Comparable(envelope.NativeState))throw new InvalidDataException("Injected snapshot differs from captured native state at "+envelope.DecisionId);
        return run;
    }
    // Shared by SnapshotPlayback (adds a shield to keep this read-only) and
    // SnapshotResume (uses it as-is, for real input). A real Godot NCombatRoom
    // scene — card/creature nodes bound in — turns out to not just be for
    // display: PlayCardAction's execution itself reaches into the scene
    // (CardPileCmd.CreateCardNodeAndUpdateVisuals) and throws a
    // NullReferenceException without it, even headless. A normal run builds
    // this scene as a side effect of its own real combat-start; injection skips
    // that too, same pattern as everything else in Inject(). Returns null for
    // a non-combat decision (nothing to build here).
    public static async Task<NCombatRoom?> PresentCombatScene(RunState run,Envelope envelope) {
        await PreloadManager.LoadRunAssets(run.Players.Select(p=>p.Character));
        await PreloadManager.LoadActAssets(run.Act);
        NGame.Instance!.RootSceneContainer.SetCurrentScene(NRun.Create(run));
        if(run.CurrentRoom is not CombatRoom combatRoom || combatRoom.CombatState==null || envelope.Kind is not ("combat" or "card_selection"))return null;
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
        Harness.Log("snapshot_scene_verified",new{decision_id=envelope.DecisionId,kind=envelope.Kind,hand=run.Players[0].PlayerCombatState?.Hand.Cards.Count,creatures=combatRoom.CombatState.Creatures.Count});
        return scene;
    }
    public static string Comparable(string json) {
        var obj=System.Text.Json.Nodes.JsonNode.Parse(json)!.AsObject();
        foreach(string key in new[]{"nextChoiceIds","nextRewardIds","lastExecutedHookId","lastExecutedActionId"})obj.Remove(key);
        return obj.ToJsonString();
    }
    // Capture is diagnostics: a snapshot that fails to serialize or round-trip must
    // never end the run it is observing (jev-ironclad-1113-04 died at floor 30 to an
    // NRE inside Restore). Log it and play on without a snapshot for this decision.
    public static void Capture(string id,string kind,object observation)
    {
        if(!CaptureEnabled)return;
        try {CaptureOrThrow(id,kind,observation);}
        catch(Exception error) {Harness.Log("snapshot_capture_failed",new{id,kind,error=error.GetType().Name+": "+error.Message});}
    }
    static void CaptureOrThrow(string id,string kind,object observation)
    {
        var run=RunManager.Instance.DebugOnlyGetState()!;
        var graph=DecisionSnapshotGraph.Capture(run);
        graph.ExcludedRuntimeFields=graph.ExcludedRuntimeFields.Distinct().ToList();
        var bytes=JsonSerializer.SerializeToUtf8Bytes(graph,Json);
        var decoded=JsonSerializer.Deserialize<DecisionSnapshotGraph>(bytes,Json)!;
        RunState restored;
        try {restored=(RunState)decoded.Restore();}
        catch {
            File.WriteAllBytes(Path.Combine(Path.GetDirectoryName(Environment.GetEnvironmentVariable("DEALMAKER_TEST_LOG"))!,"snapshot-failed-"+id+".json"),bytes);
            throw;
        }
        string before=JsonSerializer.Serialize(NetFullCombatState.FromRun(run,null),Json);
        string after=JsonSerializer.Serialize(NetFullCombatState.FromRun(restored,null),Json);
        var originalMoves=run.Players[0].Creature.CombatState?.Enemies.Select(e=>e.Monster?.NextMove.Id).ToArray();
        var restoredMoves=restored.Players[0].Creature.CombatState?.Enemies.Select(e=>e.Monster?.NextMove.Id).ToArray();
        if(JsonSerializer.Serialize(originalMoves)!=JsonSerializer.Serialize(restoredMoves))throw new InvalidOperationException("Snapshot enemy move differs");
        var expectedRng=RunRngSet.FromSave(run.Rng.ToSerializable());
        foreach(var property in typeof(RunRngSet).GetProperties().Where(p=>p.PropertyType==typeof(MegaCrit.Sts2.Core.Random.Rng))) {
            var expected=(MegaCrit.Sts2.Core.Random.Rng)property.GetValue(expectedRng)!;
            var actual=(MegaCrit.Sts2.Core.Random.Rng)property.GetValue(restored.Rng)!;
            for(int sample=0;sample<3;sample++)if(expected.NextInt()!=actual.NextInt())throw new InvalidOperationException("Snapshot RNG stream differs: "+property.Name);
        }
        if(before!=after)throw new InvalidOperationException("Snapshot round-trip differs from native full combat state");
        string directory=Path.Combine(Path.GetDirectoryName(Environment.GetEnvironmentVariable("DEALMAKER_TEST_LOG"))!,"snapshots");Directory.CreateDirectory(directory);
        var envelope=new Envelope{DecisionId=id,Kind=kind,CombatInProgress=CombatManager.Instance.IsInProgress,Graph=graph,NativeState=before,Observation=JsonSerializer.SerializeToElement(observation),GameAssemblyHash=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(RunState).Assembly.Location)))};
        bytes=JsonSerializer.SerializeToUtf8Bytes(envelope,Json);
        using(var file=File.Create(Path.Combine(directory,id+".json.gz")))using(var zip=new GZipStream(file,CompressionLevel.Fastest))zip.Write(bytes);
        Harness.Log("snapshot_verified",new{id,kind,nodes=graph.Entries.Count,bytes=bytes.Length,excluded_runtime_fields=graph.ExcludedRuntimeFields.Count});
    }
}
