using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using Environment = System.Environment;
using System.Text.Json;
using Godot;
using HarmonyLib;
using Dealmaker;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Rooms;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Modding;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.CharacterSelect;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.ValueProps;

namespace OvernightHarness;

[ModInitializer(nameof(Initialize))]
public static class Harness
{
    public static bool RulesV2 => Environment.GetEnvironmentVariable("DEALMAKER_RULES_V2")=="1";
    public static CardModel? ActiveCard;
    public static Creature? ActiveTarget;
    static bool visualsAudited;
    public static string Policy => Environment.GetEnvironmentVariable("DEALMAKER_POLICY") ?? "balanced";
    static string? output;
    public static void Initialize()
    {
        // Fail closed: this test mod must never run against a human save directory.
        var expected = Environment.GetEnvironmentVariable("DEALMAKER_TEST_USERDIR");
        if (string.IsNullOrEmpty(expected) || Path.GetFullPath(OS.GetUserDataDir()) != Path.GetFullPath(expected))
            throw new InvalidOperationException("Overnight harness refused non-isolated user directory: " + OS.GetUserDataDir());
        if (CommandLineHelper.GetValue("force-steam") != "off")
            throw new InvalidOperationException("Overnight harness requires --force-steam=off to prevent cloud save access");
        output = Environment.GetEnvironmentVariable("DEALMAKER_TEST_LOG") ?? Path.Combine(expected,"decisions.jsonl");
        new Harmony("Dealmaker.Overnight.Isolated").PatchAll(Assembly.GetExecutingAssembly());
        if (DecisionBridge.Enabled) DecisionBridge.Start();
        ReplayOverlay.Attach();
        var modPath=typeof(Dealer).Assembly.Location;
        var manifest=Path.Combine(Path.GetDirectoryName(modPath)!,"Dealmaker.json");
        using var manifestJson=JsonDocument.Parse(File.ReadAllText(manifest));
        Log("harness",new { seed=CommandLineHelper.GetValue("seed"),policy=Policy, userdata=OS.GetUserDataDir(), baseline=manifestJson.RootElement.GetProperty("version").GetString(),pilot=DecisionBridge.Enabled?"remote-http-v1":"survival-aware-v3",quoteSmoke=Environment.GetEnvironmentVariable("DEALMAKER_QUOTE_SMOKE")=="1",modSha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(modPath))),harnessSha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Assembly.GetExecutingAssembly().Location))),paidPlays=true,defensiveCheats=false });
    }
    public static void Log(string kind,object data)
    {
        if(DecisionBridge.Enabled && kind=="run_end")DecisionBridge.SetTerminal(data);
        var line=JsonSerializer.Serialize(new {utc=DateTime.UtcNow,kind,policy=Policy,data});
        if(output!=null)File.AppendAllText(output,line+"\n");
        GD.Print("[OVERNIGHT] "+line);
    }
    public static void AuditVisuals(Player player)
    {
        if(visualsAudited)return;visualsAudited=true;
        try {
            var packed=ResourceLoader.Load<PackedScene>(CharacterArt.ScenePath("combat"));
            using(var probe=packed.Instantiate<Node2D>()) {
                probe.Visible=false;((SceneTree)Engine.GetMainLoop()).Root.AddChild(probe);
                var anim=probe.GetNode<AnimationPlayer>("AnimationPlayer");
                var figure=probe.GetNode<Sprite2D>("Visuals/DeathFigure");
                var observed=new List<object>();
                foreach(double moment in new double[]{.01,.43,.65,1.14,1.35,1.53,2.79}) {
                    anim.Play("Dead");anim.Seek(moment,true);anim.Advance(0);
                    if(figure.Texture is not AtlasTexture atlas || !figure.Visible)throw new InvalidOperationException("Approved death atlas not active");
                    observed.Add(new{time=moment,region=atlas.Region.ToString(),position=figure.Position.ToString()});
                }
                anim.Play("Idle");anim.Seek(0,true);anim.Advance(0);
                if(figure.Visible)throw new InvalidOperationException("Death figure leaked into Idle");
                Log("approved_death_audit",new{duration=anim.GetAnimation("Dead").Length,poses=observed,note="Engine animation track check; approved pose sheet, not a fresh visual review"});
                probe.GetParent().RemoveChild(probe);
            }
            var visual=NCombatRoom.Instance?.GetCreatureNode(player.Creature)?.Visuals;
            var animation=visual?.GetNodeOrNull<AnimationPlayer>("AnimationPlayer");
            var markers=new[]{"Visuals","Bounds","FormVfx","IntentPos","CenterPos","OrbPos","TalkPos"}.ToDictionary(n=>n,n=>visual?.GetNodeOrNull("%"+n)!=null);
            var counters=UiHelper.FindAll<NEnergyCounter>(((SceneTree)Engine.GetMainLoop()).Root);
            Log("visual_audit",new {visualType=visual?.GetType().FullName,visualName=visual?.Name.ToString(),animationNames=animation?.GetAnimationList(),playing=animation?.CurrentAnimation,markers,energyCounters=counters.Select(e=>new {name=e.Name.ToString(),label=e.GetNodeOrNull("Label")!=null,layers=e.GetNodeOrNull("%Layers")!=null,rotation=e.GetNodeOrNull("%RotationLayers")!=null,back=e.GetNodeOrNull("%EnergyVfxBack")!=null,front=e.GetNodeOrNull("%EnergyVfxFront")!=null}).ToArray(),note="Headless node binding audit, not a rendered appearance review"});
        }catch(Exception e){Log("visual_audit_error",new {error=e.ToString()});}
    }
    public static object Card(CardModel c)=>new {id=c.Id.Entry,title=c.Title,upgraded=c.IsUpgraded,type=c.Type.ToString(),cost=c.EnergyCost.GetAmountToSpend()};
    public static object State(Player p)=>new {
        actualSeed=p.RunState.Rng.StringSeed,floor=RunManager.Instance.DebugOnlyGetState()?.TotalFloor,hp=p.Creature.CurrentHp,maxHp=p.Creature.MaxHp,block=p.Creature.Block,
        energy=p.PlayerCombatState?.Energy,gold=p.Gold,
        strength=p.Creature.GetPower<StrengthPower>()?.Amount??0,wall=p.Creature.GetPower<WallPower>()?.Amount??0,
        boast=p.Creature.GetPower<DealLedger>()?.Boasts.Stacks??0,attacks=p.Creature.GetPower<DealLedger>()?.Boasts.Attacks??0,
        hand=p.PlayerCombatState?.Hand.Cards.Select(Card).ToArray(),deck=p.Deck.Cards.Select(Card).ToArray(),relics=p.Relics.Select(r=>r.Id.Entry).ToArray(),
        enemies=p.Creature.CombatState?.HittableEnemies.Select(e=>new {id=e.Monster?.Id.Entry,hp=e.CurrentHp,block=e.Block,intents=e.Monster?.NextMove.Intents.Select(i=>new {type=i.IntentType.ToString(),damage=i is AttackIntent a?a.GetTotalDamage(new[]{p.Creature},e):0}).ToArray()}).ToArray()
    };
    public static string Text(CardModel c)=>c is DealerCard d?d.Def.Text:c is BigPromise?"Boast":c is FirmHandshake?"Favor":"";
    public static bool ProvidesBoast(CardModel c)=>c is BigPromise || c is DealerCard d && d.Number is 1 or 11 or 21 or 31 or 34 or 35 or 36 or 60 or 62 or 68;
    public static decimal PreviewDamage(CardModel card,Creature target)
    {
        if(card.Type!=CardType.Attack||!card.DynamicVars.TryGetValue("Damage",out var damage))return 0;
        return Hook.ModifyDamage(card.Owner.RunState,card.CombatState,target,card.Owner.Creature,damage.BaseValue,ValueProp.Move,card,ModifyDamageHookType.All,CardPreviewMode.Normal,out _);
    }
    public static Creature? Target(CardModel card,Player p)
    {
        var enemies=p.Creature.CombatState?.HittableEnemies.ToList();
        if(enemies==null)return null;
        return enemies.Where(e=>PreviewDamage(card,e)>=e.CurrentHp+e.Block).OrderByDescending(e=>e.Monster?.NextMove.Intents.OfType<AttackIntent>().Sum(i=>i.GetTotalDamage(new[]{p.Creature},e))??0).ThenBy(e=>e.CurrentHp+e.Block).FirstOrDefault()
            ??enemies.OrderBy(e=>e.CurrentHp+e.Block).FirstOrDefault();
    }
    public static double DraftScore(CardModel c)
    {
        var text=Text(c);double score=0;
        if(c.Type==CardType.Power)score+=1;
        string keyword=Policy switch {"boast"=>"Boast","wall"=>"Wall","favor"=>"Favor","status"=>"Spin",_=>""};
        if(keyword!=""&&text.Contains(keyword))score+=5;
        if(c is DealerCard d)score+= d.Def.Damage>0?1:0;
        return score;
    }
    public static double PlayScore(CardModel c,Player p)
    {
        var text=Text(c);var hand=PileType.Hand.GetPile(p).Cards;var ledger=p.Creature.GetPower<DealLedger>();
        double score=DraftScore(c);
        if(c.Type==CardType.Power)score+=15;
        if(c is Favor)score+=8;
        if(c.Type==CardType.Attack)score+=4;
        if(text.Contains("Favor"))score+=2;
        if(ProvidesBoast(c)) {
            int remainingEnergy=(p.PlayerCombatState?.Energy??0)-c.EnergyCost.GetAmountToSpend();
            var attacks=hand.Where(a=>a!=c&&a.Type==CardType.Attack&&!ProvidesBoast(a)).OrderBy(a=>a.EnergyCost.GetAmountToSpend()).Take(2).ToList();
            bool payable=attacks.Count==2&&attacks.Sum(a=>a.EnergyCost.GetAmountToSpend())<=remainingEnergy;
            score+=payable?30:-80;
            if((ledger?.Boasts.Attacks??0)>0)score-=25;
        }
        if((ledger?.Boasts.Stacks??0)>0&&c.Type==CardType.Attack&&!ProvidesBoast(c))score+=25;
        int uncovered=PolicySelections.Incoming(p)-p.Creature.Block-(p.Creature.GetPower<WallPower>()?.Amount??0);
        if(c.GainsBlock&&uncovered>0)score+=7;
        if(c is DealerDefend&&uncovered<=0)score-=100;
        if(c.Type==CardType.Attack&&c is not Favor&&c.DynamicVars.TryGetValue("Damage",out var damage))
            score+=Math.Min(5,(double)damage.BaseValue/4);
        bool lethalThreat=uncovered>=p.Creature.CurrentHp;
        bool highPressure=uncovered>=Math.Max(8,p.Creature.CurrentHp/3);
        if(highPressure&&c.Type==CardType.Power)score-=25;
        if(highPressure&&ProvidesBoast(c))score=Math.Min(score,15);
        double defense=c is Favor?3:c.DynamicVars.TryGetValue("Block",out var block)?(double)block.BaseValue:0;
        if(c is DealerCard direct&&direct.Number is 4 or 14 or 28 or 42)
            defense+=direct.DynamicVars["Effect"].IntValue*(direct.Number==28?(p.Creature.CombatState?.HittableEnemies.Count??0):1);
        if(lethalThreat&&defense>0)score=Math.Max(score,60+Math.Min(defense,20));
        var target=Target(c,p);
        int removedIncoming=target?.Monster?.NextMove.Intents.OfType<AttackIntent>().Sum(i=>i.GetTotalDamage(new[]{p.Creature},target))??0;
        if(c.Type==CardType.Attack&&target!=null&&PreviewDamage(c,target)>=target.CurrentHp+target.Block&&(!lethalThreat||removedIncoming>0||p.Creature.CombatState?.HittableEnemies.Count==1))score+=200;
        if(text.Contains("Wall"))score+=Policy=="wall"?10:3;
        return score;
    }
}

[HarmonyPatch(typeof(NGame),nameof(NGame.IsReleaseGame))]
static class EnableAutoSlay {static bool Prefix(ref bool __result){__result=false;return false;}}

[HarmonyPatch(typeof(NCharacterSelectScreen),"AfterInitialized")]
static class PreserveRequestedSeed
{
    static void Postfix()=>NGame.Instance!.DebugSeedOverride=CommandLineHelper.GetValue("seed")??throw new InvalidOperationException("Controlled playtest requires seed");
}

[HarmonyPatch(typeof(NCharacterSelectButton),nameof(NCharacterSelectButton.Select))]
static class ForceRequestedCharacter
{
    static bool Prefix(NCharacterSelectButton __instance)
    {
        string requested=Environment.GetEnvironmentVariable("DEALMAKER_CHARACTER")??"dealmaker";
        bool Matches(NCharacterSelectButton button)=>requested=="dealmaker" ? button.Character is Dealer : button.Character.GetType().Name.Equals(requested,StringComparison.OrdinalIgnoreCase);
        if(Matches(__instance))return true;
        var root=((SceneTree)Engine.GetMainLoop()).Root;
        var dealer=UiHelper.FindAll<NCharacterSelectButton>(root).FirstOrDefault(Matches);
        if(dealer==null)throw new InvalidOperationException("Requested character button missing: "+requested);
        dealer.Select();return false;
    }
}

[HarmonyPatch(typeof(CombatRoomHandler),nameof(CombatRoomHandler.HandleAsync))]
static class PaidCombat
{
    static bool Prefix(Rng random,CancellationToken ct,ref Task __result){__result=Run(random,ct);return false;}
    public static async Task Run(Rng random,CancellationToken ct)
    {
        if (DecisionBridge.Enabled) { await RemotePilot.Combat(ct); return; }
        await WaitHelper.Until(()=>CombatManager.Instance.IsInProgress,ct,AutoSlayConfig.nodeWaitTimeout,"Combat not started");
        var player=LocalContext.GetMe(RunManager.Instance.DebugOnlyGetState()) ?? throw new InvalidOperationException("No local player");
        Harness.Log("combat_start",Harness.State(player));
        int turn=0;
        while(CombatManager.Instance.IsInProgress&&turn<100)
        {
            await WaitHelper.Until(()=>player.PlayerCombatState?.Phase==PlayerTurnPhase.Play||!CombatManager.Instance.IsInProgress,ct,TimeSpan.FromSeconds(30),"Play phase missing");
            if(!CombatManager.Instance.IsInProgress)break;
            Harness.AuditVisuals(player);
            if(Environment.GetEnvironmentVariable("DEALMAKER_QUOTE_SMOKE")=="1")
            {
                var path=Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)!,"QuoteSmoke.dll");
                var assembly=System.Runtime.Loader.AssemblyLoadContext.GetLoadContext(typeof(Harness).Assembly)!.LoadFromAssemblyPath(path);
                var task=(Task)assembly.GetType("DealmakerQuoteSmoke.QuoteScenario")!.GetMethod("Run")!.Invoke(null,new object[]{player,ct})!;
                await task;Harness.Log("quote_smoke_completed",new {functionalFixture=true,notBalanceRun=true});
                NGame.Instance!.GetTree().Quit(0);await Task.Delay(Timeout.Infinite,ct);
            }
            turn++;AutoSlayer.CurrentWatchdog?.Reset("Paid combat turn "+turn);
            Harness.Log("turn",new {turn,state=Harness.State(player)});
            var room=RunManager.Instance.DebugOnlyGetState()?.CurrentRoom?.RoomType.ToString();
            if(player.Creature.CurrentHp<player.Creature.MaxHp/2||room is "Elite" or "Boss")
            {
                foreach(var potion in player.Potions.ToList())
                {
                    if(!CombatManager.Instance.IsInProgress||player.PlayerCombatState?.Phase!=PlayerTurnPhase.Play)break;
                    Creature? target=potion.TargetType==TargetType.AnyEnemy?player.Creature.CombatState!.HittableEnemies.OrderBy(e=>e.CurrentHp).FirstOrDefault():potion.TargetType.IsSingleTarget()?player.Creature:null;
                    if(!potion.IsValidTarget(target))continue;
                    Harness.Log("potion",new {id=potion.Id.Entry,reason="Below half health or elite/boss combat",target=target?.Monster?.Id.Entry});
                    potion.EnqueueManualUse(target);
                    await Task.Delay(150,ct);
                    await RunManager.Instance.ActionExecutor.FinishedExecutingActions();
                }
            }
            var attempted=new HashSet<CardModel>();
            for(int plays=0;plays<100&&CombatManager.Instance.IsInProgress;plays++)
            {
                ct.ThrowIfCancellationRequested();
                if(player.PlayerCombatState?.Phase!=PlayerTurnPhase.Play)break;
                var cards=PileType.Hand.GetPile(player).Cards.Where(c=>c.CanPlay(out _,out _)&&!attempted.Contains(c)).OrderByDescending(c=>Harness.PlayScore(c,player)).ToList();
                if(cards.Count==0||Harness.PlayScore(cards[0],player)<-20)break;
                var card=cards[0];attempted.Add(card);
                Creature? target=card.TargetType==TargetType.AnyEnemy?Harness.Target(card,player):null;
                if(!card.IsValidTarget(target))continue;
                Harness.Log("decision",new {turn,card=Harness.Card(card),target=target?.Monster?.Id.Entry,score=Harness.PlayScore(card,player),uncoveredIncoming=PolicySelections.Incoming(player)-player.Creature.Block-(player.Creature.GetPower<WallPower>()?.Amount??0),reason="Visible lethal attack or immediate survival defense first; reduce setup under pressure; otherwise payable Boast and policy support",before=Harness.State(player)});
                PolicySelections.BeginPlay();
                Harness.ActiveCard=card;
                Harness.ActiveTarget=target;
                RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(new PlayCardAction(card,target));
                await Task.Delay(150,ct);
                await RunManager.Instance.ActionExecutor.FinishedExecutingActions();
                Harness.ActiveCard=null;
                Harness.ActiveTarget=null;
                Harness.Log("after_play",new {turn,card=card.Id.Entry,state=Harness.State(player)});
                AutoSlayer.CurrentWatchdog?.Reset("Paid card "+card.Id.Entry);
            }
            if(CombatManager.Instance.IsInProgress&&player.PlayerCombatState?.Phase==PlayerTurnPhase.Play)
            {
                Harness.Log("end_turn",new {turn,state=Harness.State(player)});
                int previousTurn=player.PlayerCombatState.TurnNumber;
                PlayerCmd.EndTurn(player,canBackOut:false);
                await Task.Delay(150,ct);
                await WaitHelper.Until(()=>player.PlayerCombatState?.Phase!=PlayerTurnPhase.Play||player.PlayerCombatState?.TurnNumber>previousTurn||!CombatManager.Instance.IsInProgress,ct,TimeSpan.FromSeconds(10),"Turn did not end");
            }
        }
        Harness.Log("combat_end",new {turn,state=Harness.State(player),dead=player.Creature.IsDead});
        if(player.Creature.IsDead)
        {
            Harness.Log("run_end",new {outcome="death",floor=RunManager.Instance.DebugOnlyGetState()?.TotalFloor,deck=player.Deck.Cards.Select(Harness.Card).ToArray()});
            NGame.Instance!.GetTree().Quit(0);
            await Task.Delay(Timeout.Infinite,ct);
        }
    }
}

[HarmonyPatch(typeof(EventRoomHandler),"HandleEventCombat")]
static class PaidEventCombat
{
    static bool Prefix(CancellationToken ct,ref Task __result){__result=PaidCombat.Run(new Rng(0),ct);return false;}
}

[HarmonyPatch(typeof(AutoSlayLog),nameof(AutoSlayLog.RunCompleted))]
static class CompletionLog
{
    static void Prefix(string seed)=>Harness.Log("driver_completed",new {seed,note="Driver completion alone is not proof of victory; inspect final room/outcome."});
}
[HarmonyPatch(typeof(AutoSlayLog),nameof(AutoSlayLog.RunFailed))]
static class FailureLog
{
    static void Prefix(string seed,Exception ex)=>Harness.Log("harness_failure",new {seed,error=ex.ToString()});
}
[HarmonyPatch(typeof(AutoSlayLog),nameof(AutoSlayLog.EnterRoom))]
static class RoomLog
{
    static void Prefix(MegaCrit.Sts2.Core.Rooms.RoomType type,int act,int floor)=>Harness.Log("room",new {type=type.ToString(),act=act+1,floor});
}

[HarmonyPatch]
static class RemoveSmokeFloorCap
{
    static MethodBase TargetMethod()=>AccessTools.Method(AccessTools.Method(typeof(AutoSlayer),"PlayRunAsync").GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType,"MoveNext");
    static IEnumerable<CodeInstruction> Transpiler(IEnumerable<CodeInstruction> instructions)
    {
        int changes=0;
        foreach(var instruction in instructions) {
            if(instruction.LoadsConstant(49)) {instruction.opcode=OpCodes.Ldc_I4;instruction.operand=999;changes++;}
            yield return instruction;
        }
        if(changes!=1)throw new InvalidOperationException("Unexpected AutoSlay floor-cap IL: "+changes);
    }
}

[HarmonyPatch(typeof(AutoSlayLog),nameof(AutoSlayLog.Action))]
static class ExplicitOutcome
{
    static void Prefix(string action)
    {
        if(action=="Victory! Run completed and returned to main menu")Harness.Log("run_end",new {outcome="victory",evidence=action});
        if(action.Contains("max floor reached"))Harness.Log("run_end",new {outcome="abandoned_by_driver",evidence=action});
    }
}

[HarmonyPatch(typeof(CardRewardScreenHandler),nameof(CardRewardScreenHandler.HandleAsync))]
static class DraftPolicy
{
    static bool Prefix(Rng random,CancellationToken ct,ref Task __result){__result=DecisionBridge.Enabled ? RemoteScreens.Run("card_reward",ct) : Run(ct);return false;}
    static async Task Run(CancellationToken ct)
    {
        var screen=AutoSlayer.GetCurrentScreen<NCardRewardSelectionScreen>();
        await Task.Delay(400,ct);
        var options=UiHelper.FindAll<NCardHolder>(screen).Where(h=>h.CardModel!=null).ToList();
        if(options.Count==0)return;
        var selected=options.OrderByDescending(h=>Harness.DraftScore(h.CardModel!)).First();
        Harness.Log("draft",new {options=options.Select(h=>Harness.Card(h.CardModel!)).ToArray(),selected=Harness.Card(selected.CardModel!),reason="Preference policy; other reward and event choices use seeded AutoSlay defaults"});
        selected.EmitSignal(NCardHolder.SignalName.Pressed,selected);
        await WaitHelper.Until(()=>!GodotObject.IsInstanceValid(screen)||!screen.IsVisibleInTree(),ct,TimeSpan.FromSeconds(10),"Reward screen not closed");
    }
}

[HarmonyPatch(typeof(RestSiteRoomHandler),nameof(RestSiteRoomHandler.HandleAsync))]
static class RestPolicy
{
    static bool Prefix(Rng random,CancellationToken ct,ref Task __result){__result=DecisionBridge.Enabled ? RemoteScreens.Run("rest",ct) : Run(ct);return false;}
    static async Task Run(CancellationToken ct)
    {
        var root=((SceneTree)Engine.GetMainLoop()).Root;
        var room=await WaitHelper.ForNode<MegaCrit.Sts2.Core.Nodes.Rooms.NRestSiteRoom>(root,"/root/Game/RootSceneContainer/Run/RoomContainer/RestSiteRoom",ct);
        var options=UiHelper.FindAll<MegaCrit.Sts2.Core.Nodes.RestSite.NRestSiteButton>(room).Where(b=>b.Option.IsEnabled).ToList();
        if(options.Count==0)return;
        var p=LocalContext.GetMe(RunManager.Instance.DebugOnlyGetState()) ?? throw new InvalidOperationException("Rest has no local player");
        bool heal=p.Creature.CurrentHp<0.6m*p.Creature.MaxHp;
        var chosen=options.FirstOrDefault(b=>b.Option.GetType().Name==(heal?"HealRestSiteOption":"SmithRestSiteOption"))??options[0];
        Harness.Log("rest",new{hp=p.Creature.CurrentHp,maxHp=p.Creature.MaxHp,chosen=chosen.Option.GetType().Name,reason="Rest below 60% HP, otherwise Smith when available"});
        await UiHelper.Click(chosen);
        await WaitHelper.Until(()=>room.ProceedButton.IsEnabled||(MegaCrit.Sts2.Core.Nodes.Screens.Overlays.NOverlayStack.Instance?.ScreenCount??0)>0,ct,TimeSpan.FromSeconds(10),"Rest option did not respond");
        if((MegaCrit.Sts2.Core.Nodes.Screens.Overlays.NOverlayStack.Instance?.ScreenCount??0)>0)return;
        await UiHelper.Click(room.ProceedButton);
    }
}

[HarmonyPatch(typeof(DeckUpgradeScreenHandler),nameof(DeckUpgradeScreenHandler.HandleAsync))]
static class UpgradePolicy
{
    static bool Prefix(Rng random,CancellationToken ct,ref Task __result){__result=DecisionBridge.Enabled ? RemoteScreens.Run("upgrade",ct) : Run(ct);return false;}
    static async Task Run(CancellationToken ct)
    {
        var screen=AutoSlayer.GetCurrentScreen<NDeckUpgradeSelectScreen>();
        var cards=UiHelper.FindAll<NGridCardHolder>(screen).Where(c=>c.CardModel!=null).ToList();
        if(cards.Count==0)return;
        var selected=cards.OrderByDescending(c=>Harness.DraftScore(c.CardModel!)+(c.CardModel is BigPromise or FirmHandshake?2:0)+(c.CardModel is DealerStrike or DealerDefend?-10:0)).First();
        Harness.Log("upgrade",new{offered=cards.Select(c=>Harness.Card(c.CardModel!)).ToArray(),selected=Harness.Card(selected.CardModel!),reason="Highest draft-policy score; unique starters favored over ordinary basics"});
        selected.EmitSignal(NCardHolder.SignalName.Pressed,selected);
        Control? preview=null;
        await WaitHelper.Until(()=>{preview=new[]{screen.GetNodeOrNull<Control>("%UpgradeSinglePreviewContainer"),screen.GetNodeOrNull<Control>("%UpgradeMultiPreviewContainer")}.FirstOrDefault(c=>c!=null&&c.Visible);return preview!=null;},ct,TimeSpan.FromSeconds(5),"Upgrade preview missing");
        var confirm=preview!.GetNode<MegaCrit.Sts2.Core.Nodes.CommonUi.NConfirmButton>("Confirm");
        await WaitHelper.Until(()=>confirm.IsEnabled,ct,TimeSpan.FromSeconds(5),"Upgrade confirmation disabled");
        await UiHelper.Click(confirm);
        await WaitHelper.Until(()=>!GodotObject.IsInstanceValid(screen)||!screen.IsVisibleInTree(),ct,TimeSpan.FromSeconds(10),"Upgrade screen not closed");
    }
}

// New runs opt in; archived replays keep their original first-room behavior.
[HarmonyPatch(typeof(AutoSlayer), "PlayMainMenuAsync")]
static class UnlockStartingAncient
{
    static void Prefix() {
        if(Harness.RulesV2)
            MegaCrit.Sts2.Core.Saves.SaveManager.Instance.ObtainEpochOverride(
                MegaCrit.Sts2.Core.Timeline.EpochModel.GetId<MegaCrit.Sts2.Core.Timeline.Epochs.NeowEpoch>(),
                MegaCrit.Sts2.Core.Saves.EpochState.Revealed);
    }
}
