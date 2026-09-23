using Dealmaker;
using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;

namespace OvernightHarness;
public static class RemotePilot
{
    public static Player Player => LocalContext.GetMe(RunManager.Instance.DebugOnlyGetState()) ?? throw new InvalidOperationException("No player");
    public static object Card(CardModel c,Creature? target=null)=>new {
        id=c.Id.Entry,name=c.Title,type=c.Type.ToString(),upgraded=c.IsUpgraded,cost=c.EnergyCost.GetAmountToSpend(),
        text=c.GetDescriptionForPile(c.Pile?.Type??PileType.None,target),keywords=c.Keywords.Select(k=>k.ToString()).ToArray(),
        preview_damage_per_hit=target==null?(decimal?)null:Harness.RulesV2?DamageBeforeHpCaps(c,target):Harness.PreviewDamage(c,target),
        variables=c.DynamicVars.ToDictionary(v=>v.Key,v=>v.Value.BaseValue)
    };
    // Unknown is not zero. These previews are damage, not HP loss after block/caps.
    static decimal? DamageBeforeHpCaps(CardModel card,Creature target) {
        if(card.Type!=CardType.Attack)return null;
        decimal amount;var props=MegaCrit.Sts2.Core.ValueProps.ValueProp.Move;
        if(card.DynamicVars.TryGetValue("CalculatedDamage",out var value) && value is MegaCrit.Sts2.Core.Localization.DynamicVars.CalculatedDamageVar calculated) {
            amount=calculated.Calculate(target);props=calculated.Props;
        } else if(card.DynamicVars.TryGetValue("Damage",out var damage))amount=damage.BaseValue;
        else return null;
        return MegaCrit.Sts2.Core.Hooks.Hook.ModifyDamage(card.Owner.RunState,card.CombatState,target,card.Owner.Creature,amount,props,card,MegaCrit.Sts2.Core.Hooks.ModifyDamageHookType.All,CardPreviewMode.Normal,out _);
    }
    public static object Creature(Creature c)=>new {name=c.Monster?.Id.Entry??"player",hp=c.CurrentHp,max_hp=c.MaxHp,block=c.Block,
        powers=c.Powers.Select(p=>new {id=p.Id.Entry,amount=p.Amount,text=p.DumbHoverTip.Description}).ToArray()};
    public static object State()
    {
        var p=Player;var pc=p.PlayerCombatState;var run=RunManager.Instance.DebugOnlyGetState()!;
        object[] Pile(PileType t)=>t.GetPile(p).Cards.OrderBy(c=>c.Id.Entry).ThenBy(c=>c.IsUpgraded).Select(c=>Card(c)).ToArray();
        var snapshot = new {seed=run.Rng.StringSeed,floor=run.TotalFloor,act=run.CurrentActIndex+1,room=run.CurrentRoom?.RoomType.ToString(),
            player=Creature(p.Creature),gold=p.Gold,energy=pc?.Energy,turn=pc?.TurnNumber,
            boast=p.Creature.GetPower<DealLedger>()?.Boasts.Stacks??0,boast_attacks=p.Creature.GetPower<DealLedger>()?.Boasts.Attacks??0,
            hand=pc?.Hand.Cards.Select((c,i)=>new {index=i,card=Card(c)}).ToArray(),
            draw_pile_unordered=pc==null?null:Pile(PileType.Draw),discard=pc==null?null:Pile(PileType.Discard),exhaust=pc==null?null:Pile(PileType.Exhaust),
            deck=p.Deck.Cards.Select(c=>Card(c)).ToArray(),relics=p.Relics.Select(r=>new {id=r.Id.Entry,text=r.DynamicDescription.GetFormattedText()}).ToArray(),
            potions=p.Potions.Select(po=>new {id=po.Id.Entry,text=po.DynamicDescription.GetFormattedText(),usage=po.Usage.ToString()}).ToArray(),
            enemies=p.Creature.CombatState?.HittableEnemies.Select((e,i)=>new {index=i,creature=Creature(e),
                intents=e.Monster?.NextMove.Intents.Select(intent=>new {type=intent.IntentType.ToString(),total_damage=intent is AttackIntent a?a.GetTotalDamage(new[]{p.Creature},e):0}).ToArray()}).ToArray()};
        // Preserve old Dealmaker recordings exactly; base characters receive
        // their additional resources instead of silently hiding them from Jev.
        if (p.Character is Dealer) return snapshot;
        var expanded=System.Text.Json.JsonSerializer.Deserialize<Dictionary<string,object?>>(System.Text.Json.JsonSerializer.Serialize(snapshot))!;
        if(System.Environment.GetEnvironmentVariable("DEALMAKER_ACT1_OVERGROWTH")=="1")expanded["act_id"]=run.Act.Id.Entry;
        // This boss identity is visible in the map/top-bar icon. No future room RNG is exposed.
        if(System.Environment.GetEnvironmentVariable("DEALMAKER_PLANNING_CONTEXT")=="1") {
            expanded["known_boss"]=run.Act.BossEncounter?.Id.Entry;
            expanded["potion_slots_free"]=p.PotionSlots.Count(po=>po==null);
        }
        expanded["character"]=p.Character.GetType().Name;
        expanded["stars"]=pc?.Stars;
        expanded["orb_slots"]=pc?.OrbQueue.Capacity;
        expanded["orbs_in_order"]=pc?.OrbQueue.Orbs.Select(o=>new{id=o.Id.Entry,passive=o.PassiveVal,evoke=o.EvokeVal,text=o.SmartDescription.GetFormattedText()}).ToArray();
        expanded["osty"]=p.Osty==null?null:Creature(p.Osty);
        return expanded;
    }
    public static async Task<IEnumerable<CardModel>> Select(List<CardModel> cards,int min,int max)
    {
        max=Math.Min(max,cards.Count);min=Math.Min(min,max);var chosen=new List<CardModel>();
        while(chosen.Count<max) {
            var remaining=cards.Except(chosen).ToList();
            var opts=remaining.Select(c=>(object)new {action="select_card",card=Card(c)}).ToList();
            if(chosen.Count>=min)opts.Add(new {action="confirm_selection"});
            int i=await DecisionBridge.Choose("card_selection",new {game=State(),prompt=SelectionContext.Prompt,source=Harness.ActiveCard==null?null:Card(Harness.ActiveCard),min,max,selected=chosen.Select(c=>Card(c)).ToArray()},opts,CancellationToken.None);
            if(i==remaining.Count)break;chosen.Add(remaining[i]);
        }
        return chosen;
    }
    public static void AddPotions(List<object> opts,List<Func<Task>> apply,bool combat,CancellationToken ct,bool shop=false)
    {
        var p=Player;if(!p.CanRemovePotions)return;
        var candidates=new List<Creature?>{null,p.Creature};
        if(combat)candidates.AddRange(p.Creature.CombatState!.HittableEnemies);
        foreach(var potion in p.Potions.ToArray()) {
            if(potion.IsQueued)continue;
            var po=potion;
            opts.Add(new {action="discard_potion",slot=p.GetPotionSlotIndex(po),id=po.Id.Entry,text=po.DynamicDescription.GetFormattedText()});
            apply.Add(async ()=>{RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(new DiscardPotionGameAction(p,(uint)p.GetPotionSlotIndex(po),combat));await Task.Delay(100,ct);await RunManager.Instance.ActionExecutor.FinishedExecutingActions();});
            if(!po.PassesCustomUsabilityCheck || po.Usage.ToString() is "Automatic" or "None" || (!combat&&po.Usage.ToString()!="AnyTime") || (po.TargetType==TargetType.TargetedNoCreature&&!shop))continue;
            foreach(var target in candidates.Where(po.IsValidTarget)) {
                var victim=target;
                opts.Add(new {action="use_potion",slot=p.GetPotionSlotIndex(po),id=po.Id.Entry,text=po.DynamicDescription.GetFormattedText(),target=target==null?null:Creature(target),enemy_index=target==null?-1:p.Creature.CombatState?.HittableEnemies.ToList().IndexOf(target)??-1});
                apply.Add(async ()=>{if(!p.Potions.Contains(po)||!po.PassesCustomUsabilityCheck||!po.IsValidTarget(victim))throw new InvalidOperationException("Potion became illegal");po.EnqueueManualUse(victim);await Task.Delay(100,ct);await RunManager.Instance.ActionExecutor.FinishedExecutingActions();});
            }
        }
    }
    public static async Task Combat(CancellationToken ct)
    {
        await WaitHelper.Until(()=>CombatManager.Instance.IsInProgress,ct,TimeSpan.FromSeconds(30),"Combat not ready");
        var p=Player;Harness.Log("combat_start",State());int actions=0;
        while(CombatManager.Instance.IsInProgress) {
            await WaitHelper.Until(()=>p.PlayerCombatState?.Phase==PlayerTurnPhase.Play||!CombatManager.Instance.IsInProgress,ct,TimeSpan.FromSeconds(60),"Player turn missing");
            if(!CombatManager.Instance.IsInProgress)break;
            if(System.Environment.GetEnvironmentVariable("DEALMAKER_DEATH_AUDIT")=="1")Harness.AuditVisuals(p);
            if(++actions>3000)throw new InvalidOperationException("Combat action budget exhausted");
            var opts=new List<object>();var apply=new List<Func<Task>>();
            var enemies=p.Creature.CombatState!.HittableEnemies.ToList();
            var candidates=new List<Creature?>{null,p.Creature};candidates.AddRange(enemies);
            foreach(var c in p.PlayerCombatState!.Hand.Cards.ToArray()) {
                if(!c.CanPlay(out _,out _))continue;
                foreach(var target in candidates.Where(c.IsValidTarget)) {
                    var card=c;var victim=target;
                    opts.Add(new {action="play_card",hand_index=p.PlayerCombatState.Hand.Cards.ToList().IndexOf(c),card=Card(c,target),target=target==null?null:Creature(target),enemy_index=target==null?-1:enemies.IndexOf(target)});
                    apply.Add(async ()=>{
                        if(!p.PlayerCombatState.Hand.Cards.Contains(card)||!card.CanPlay(out _,out _)||!card.IsValidTarget(victim))throw new InvalidOperationException("Card became illegal");
                        Harness.ActiveCard=card;Harness.ActiveTarget=victim;
                        try {RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(new PlayCardAction(card,victim));await Task.Delay(100,ct);await RunManager.Instance.ActionExecutor.FinishedExecutingActions();}
                        finally {Harness.ActiveCard=null;Harness.ActiveTarget=null;}
                    });
                }
            }
            AddPotions(opts,apply,true,ct);
            opts.Add(new {action="end_turn"});apply.Add(async ()=>{
                int turn=p.PlayerCombatState.TurnNumber;PlayerCmd.EndTurn(p,canBackOut:false);await Task.Delay(100,ct);
                await WaitHelper.Until(()=>!CombatManager.Instance.IsInProgress||p.PlayerCombatState.Phase!=PlayerTurnPhase.Play||p.PlayerCombatState.TurnNumber>turn,ct,TimeSpan.FromSeconds(30),"End turn failed");
            });
            int selected=await DecisionBridge.Choose("combat",State(),opts,ct);await apply[selected]();Harness.Log("remote_after_action",State());
        }
        Harness.Log("combat_end",State());
        if(p.Creature.IsDead){Harness.Log("run_end",new {outcome="death",floor=p.RunState.TotalFloor});NGame.Instance!.GetTree().Quit(0);await Task.Delay(Timeout.Infinite,ct);}
    }
}
