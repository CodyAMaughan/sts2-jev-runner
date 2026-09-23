using System.Reflection;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.AutoSlay.Handlers;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Rooms;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Entities.RestSite;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Relics;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using MegaCrit.Sts2.Core.Runs;

namespace OvernightHarness;
public static class RemoteScreens
{
    static IEnumerable<Node> Walk(Node n) {yield return n;foreach(var c in n.GetChildren())foreach(var d in Walk(c))yield return d;}
    static bool Visible(Node n)=>n is not CanvasItem c || c.IsVisibleInTree();
    public static string Text(Node n)=>string.Join(" | ",Walk(n).Where(Visible).Select(x=>x switch {Label l=>l.Text,RichTextLabel l=>l.Text,_=>""}).Where(x=>!string.IsNullOrWhiteSpace(x)).Distinct());
    static object Model(AbstractModel? m)=>m switch {
        CardModel c=>RemotePilot.Card(c),RelicModel r=>new {id=r.Id.Entry,text=r.DynamicDescription.GetFormattedText()},
        PotionModel p=>new {id=p.Id.Entry,text=p.DynamicDescription.GetFormattedText()},_=>new {id=m?.Id.Entry}
    };
    public static async Task Run(string kind,CancellationToken ct)
    {
        await Task.Delay(350,ct);
        Node root=((SceneTree)Engine.GetMainLoop()).Root;
        bool openedShop=false,openedChest=false;
        for(int step=0;step<150;step++) {
            ct.ThrowIfCancellationRequested();
            // Events can await a virtual card selector without opening an overlay.
            // Let that nested choice finish before reading fresh room options.
            if(DecisionBridge.HasPending) {
                await WaitHelper.Until(()=>!DecisionBridge.HasPending,ct,TimeSpan.FromMinutes(4),"Nested card decision did not finish");
                await Task.Delay(150,ct);
            }
            var overlay=NOverlayStack.Instance?.Peek() as Node;
            bool roomKind=kind is "rest" or "event" or "shop" or "treasure";
            if(roomKind && overlay!=null)return;
            if(kind!="map" && (NMapScreen.Instance?.IsOpen??false))return;
            if(kind=="event" && CombatManager.Instance.IsInProgress){await RemotePilot.Combat(ct);await Task.Delay(500,ct);continue;}
            Node? scope=kind switch {
                "map"=>NMapScreen.Instance,
                "rest"=>root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/RestSiteRoom"),
                "event"=>root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom"),
                "shop"=>root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/MerchantRoom"),
                "treasure"=>root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom"),_=>overlay
            };
            if(scope==null || !GodotObject.IsInstanceValid(scope) || !Visible(scope))return;
            if(kind=="shop" && !openedShop){((NMerchantRoom)scope).OpenInventory();openedShop=true;await Task.Delay(400,ct);}
            if(kind=="treasure" && !openedChest){await UiHelper.Click(scope.GetNode<NClickableControl>("Chest"));openedChest=true;await Task.Delay(800,ct);}
            var opts=new List<object>();var apply=new List<Func<Task>>();
            void Add(object desc,Func<Task> act){opts.Add(desc);apply.Add(act);}
            void Click(NClickableControl b,object desc)=>Add(desc,()=>UiHelper.Click(b));
            var nodes=Walk(scope).Where(Visible).ToList();
            if(kind=="map") {
                foreach(var mp in nodes.OfType<NMapPoint>().Where(m=>m.IsEnabled)) {
                    var point=mp;
                    Click(point,new {action="map",row=point.Point.coord.row,col=point.Point.coord.col,type=point.Point.PointType.ToString(),children=point.Point.Children.Select(c=>new {row=c.coord.row,col=c.coord.col,type=c.PointType.ToString()}).ToArray()});
                }
            } else if(kind=="shop") {
                var room=(NMerchantRoom)scope;
                foreach(var slot in room.Inventory.GetAllSlots().Where(s=>s.Entry.IsStocked&&s.Entry.EnoughGold)) {
                    var entry=slot.Entry;
                    if(entry is MerchantPotionEntry && !RemotePilot.Player.HasOpenPotionSlots)continue;
                    object item=entry switch {MerchantCardEntry c=>Model(c.CreationResult?.Card),MerchantRelicEntry r=>Model(r.Model),MerchantPotionEntry p=>Model(p.Model),_=>Harness.RulesV2 && entry is MerchantCardRemovalEntry ? (object)new {name="Remove a card",text="Permanently remove one card from your deck; choose the card after purchase."} : new {name=entry.GetType().Name}};
                    // Queue purchase without awaiting: removal can open a nested choice overlay.
                    Add(new {action="purchase",cost=entry.Cost,item},()=>{_=entry.OnTryPurchaseWrapper(room.Inventory.Inventory);return Task.CompletedTask;});
                }
                Add(new {action="leave_shop"},async ()=>{var back=UiHelper.FindFirst<NBackButton>(scope);if(back!=null)await UiHelper.Click(back);await Task.Delay(250,ct);await UiHelper.Click(room.ProceedButton);});
            } else {
                var confirms=nodes.OfType<NConfirmButton>().Where(b=>b.IsEnabled).ToList();
                bool preview=confirms.Any(b=>b.GetParent().Name.ToString().Contains("Preview"));
                if(kind=="bundle") foreach(var bundle in nodes.OfType<NCardBundle>()) Click(bundle.Hitbox,new {action="choose_bundle",cards=bundle.Bundle.Select(c=>RemotePilot.Card(c)).ToArray()});
                if(kind=="crystal_sphere") foreach(var cell in nodes.OfType<NCrystalSphereCell>().Where(c=>c.Entity.IsHidden)) Click(cell,new {action="reveal_cell",x=cell.Entity.X,y=cell.Entity.Y});
                if(!preview && kind!="bundle")foreach(var holder in nodes.OfType<NCardHolder>().Where(h=>h.CardModel!=null)) {
                    var h=holder;
                    Add(new {action="select_card",card=RemotePilot.Card(h.CardModel!),selected=ReadSelected(h)},()=>{
                        var grid=UiHelper.FindFirst<NCardGrid>(scope);
                        if(kind is "simple_select" or "transform" && grid!=null)grid.EmitSignal(NCardGrid.SignalName.HolderPressed,h);
                        else h.EmitSignal(NCardHolder.SignalName.Pressed,h);
                        return Task.CompletedTask;
                    });
                }
                foreach(var button in nodes.OfType<NClickableControl>()) {
                    if(button is NButton nb && !nb.IsEnabled)continue;
                    if(button.GetType().Name.Contains("CardHighlight"))continue;
                    if(Harness.RulesV2 && button is NCardRewardAlternativeButton){Click(button,new {action="reward_alternative",text=Text(button)});continue;}
                    if(button is NEventOptionButton eb){if(!eb.Option.IsLocked)Click(button,new {action="event_option",title=eb.Option.Title.GetFormattedText(),text=Text(eb)});continue;}
                    if(button is NRestSiteButton rb){if(rb.Option.IsEnabled)Click(button,Harness.RulesV2 ? (object)new {action="rest_option",name=rb.Option.GetType().Name,text=Text(rb),effect=rb.Option.Description.GetFormattedText()} : new {action="rest_option",name=rb.Option.GetType().Name,text=Text(rb)});continue;}
                    if(button is NRewardButton reward){if(reward.Reward is MegaCrit.Sts2.Core.Rewards.PotionReward && !RemotePilot.Player.HasOpenPotionSlots)continue;Click(button,new {action="claim_reward",type=reward.Reward?.GetType().Name,text=Text(reward),item=reward.Reward is MegaCrit.Sts2.Core.Rewards.RelicReward rr?Model(rr.Relic):reward.Reward is MegaCrit.Sts2.Core.Rewards.PotionReward pr?Model(pr.Potion):null});continue;}
                    if(kind=="crystal_sphere" && button.GetType().Name=="NDivinationButton"){Click(button,new {action="divination_size",name=button.Name.ToString(),text=Text(button)});continue;}
                    var relic=UiHelper.FindFirst<NRelic>(button);
                    if(relic!=null){Click(button,new {action="take_relic",relic=Model(relic.Model)});continue;}
                    string name=button.GetType().Name;
                    if(button is NConfirmButton or NProceedButton || name.Contains("SkipButton"))Click(button,new {action=button is NConfirmButton?"confirm":button is NProceedButton?"proceed":"skip",text=Text(button)});
                }
            }
            if(opts.Count==0){
                if(Harness.RulesV2 && kind=="event") {
                    var ancient=UiHelper.FindFirst<NAncientEventLayout>(scope);
                    var dialogue=ancient?.GetNodeOrNull<NButton>("%DialogueHitbox");
                    if(dialogue!=null && dialogue.IsVisibleInTree() && dialogue.IsEnabled)await UiHelper.Click(dialogue);
                }
                await Task.Delay(150,ct);continue;
            }
            // A transitioning screen must not turn potion disposal into its only decision.
            if(kind is "rewards" or "rest" or "shop" or "treasure" or "event")RemotePilot.AddPotions(opts,apply,false,ct,kind=="shop");
            var visibleMap=kind=="map"?nodes.OfType<NMapPoint>().Select(m=>new {row=m.Point.coord.row,col=m.Point.coord.col,type=m.Point.PointType.ToString(),children=m.Point.Children.Select(c=>new {row=c.coord.row,col=c.coord.col}).ToArray()}).ToArray():null;
            var upgrades=Harness.RulesV2 && kind=="rest" ? RemotePilot.Player.Deck.Cards.Where(c=>c.IsUpgradable).Select(c=>{var clone=RunManager.Instance.DebugOnlyGetState()!.CloneCard(c);clone.UpgradeInternal();return new {before=RemotePilot.Card(c),after=RemotePilot.Card(clone)};}).ToArray():null;
            object observation=Harness.RulesV2 ? new {upgrades,game=RemotePilot.State(),screen=scope.GetType().Name,text=Text(scope),map=visibleMap} : new {game=RemotePilot.State(),screen=scope.GetType().Name,text=Text(scope),map=visibleMap};
            int selected=await DecisionBridge.Choose(kind,observation,opts,ct);
            if(kind=="map") {
                var entered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                void OnEntered()=>entered.TrySetResult();
                RunManager.Instance.RoomEntered+=OnEntered;
                try {await apply[selected]();await entered.Task.WaitAsync(TimeSpan.FromSeconds(30),ct);}
                finally {RunManager.Instance.RoomEntered-=OnEntered;}
                return;
            }
            await apply[selected]();await Task.Delay(500,ct);
            if(!GodotObject.IsInstanceValid(scope)||!Visible(scope))return;
            if(!roomKind && NOverlayStack.Instance?.Peek()!=scope)return;
        }
        throw new InvalidOperationException("Unsupported or unresponsive decision screen: "+kind);
    }
    static bool? ReadSelected(Node n)=>AccessTools.Property(n.GetType(),"IsSelected")?.GetValue(n) as bool?;
}

[HarmonyPatch]
static class RemoteScreenPatches
{
    static readonly Dictionary<Type,string> Kinds=new(){
        [typeof(MapScreenHandler)]="map",[typeof(EventRoomHandler)]="event",[typeof(ShopRoomHandler)]="shop",[typeof(TreasureRoomHandler)]="treasure",
        [typeof(ChooseARelicScreenHandler)]="relic",[typeof(RewardsScreenHandler)]="rewards",[typeof(SimpleCardSelectScreenHandler)]="simple_select",
        [typeof(DeckCardSelectScreenHandler)]="deck_select",[typeof(DeckTransformScreenHandler)]="transform",[typeof(ChooseACardScreenHandler)]="choose_card",
        [typeof(DeckEnchantScreenHandler)]="enchant",[typeof(ChooseABundleScreenHandler)]="bundle",[typeof(CrystalSphereScreenHandler)]="crystal_sphere"
    };
    static IEnumerable<MethodBase> TargetMethods()=>Kinds.Keys.Select(t=>AccessTools.Method(t,"HandleAsync"));
    static bool Prefix(object __instance,CancellationToken ct,ref Task __result) {
        if(!DecisionBridge.Enabled)return true;
        string kind=Kinds[__instance.GetType()];
        __result=RemoteScreens.Run(kind,ct);return false;
    }
}

[HarmonyPatch]
static class RemoteTimeouts
{
    static IEnumerable<MethodBase> TargetMethods()=>typeof(AutoSlayer).Assembly.GetTypes().Where(t=>!t.IsAbstract&&typeof(IHandler).IsAssignableFrom(t)).Select(t=>AccessTools.PropertyGetter(t,"Timeout")).Where(m=>m!=null);
    static void Postfix(ref TimeSpan __result){if(DecisionBridge.Enabled)__result=TimeSpan.FromHours(2);}
}
