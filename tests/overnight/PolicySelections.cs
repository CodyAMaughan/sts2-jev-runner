using Dealmaker;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Runs;

namespace OvernightHarness;

public static class PolicySelections
{
    public static int Incoming(Player p)=>p.Creature.CombatState?.HittableEnemies.Sum(e=>e.Monster?.NextMove?.Intents.OfType<AttackIntent>().Sum(i=>i.GetTotalDamage(new[]{p.Creature},e))??0)??0;
    static CardModel? lastSource;
    static int step;
    public static void BeginPlay(){lastSource=null;step=0;}
    public static IEnumerable<CardModel> Select(List<CardModel> cards,int min,int max)
    {
        var source=Harness.ActiveCard;
        if(source!=lastSource){step=0;lastSource=source;}
        step++;
        var player=LocalContext.GetMe(RunManager.Instance.DebugOnlyGetState()) ?? throw new InvalidOperationException("Selection has no local player");
        var number=(source as DealerCard)?.Number??0;
        double Value(CardModel c)=>Harness.DraftScore(c)+(c is DealerStrike or DealerDefend? -10:0)+(c.Type==CardType.Status?-50:0);
        IEnumerable<CardModel> selected;
        string reason;
        if(cards.All(c=>c is ChoiceCard))
        {
            var choices=cards.Cast<ChoiceCard>().ToList();
            ChoiceCard chosen;
            int incoming=Incoming(player),wall=player.Creature.GetPower<WallPower>()?.Amount??0;
            if(choices.Any(c=>c.Label=="Gain Block"))
            {
                bool lethal=source is Favor && Harness.ActiveTarget is {IsAlive:true} target && Harness.PreviewDamage(source,target)>=target.CurrentHp+target.Block;
                bool defend=!lethal && incoming>player.Creature.Block+wall;
                chosen=choices.FirstOrDefault(c=>c.Label==(defend?"Gain Block":"Deal damage"))??choices[0];
                reason=lethal?"Favor damage is lethal on selected target; kill before defending":"Choose Block only against uncovered displayed incoming damage; otherwise damage";
            }
            else if(choices.All(c=>c.Label.StartsWith("Spend ")))
            {
                int desired=number switch {46=>Math.Max(0,incoming-player.Creature.Block-wall-8),70=>Math.Max(0,wall-Math.Max(0,incoming-player.Creature.Block)),_=>Math.Max(0,wall-Math.Max(0,incoming-player.Creature.Block))};
                chosen=choices.Where(c=>c.Value<=desired).OrderByDescending(c=>c.Value).FirstOrDefault()??choices[0];
                reason="Spend Wall surplus after displayed incoming damage; defensive conversion only for current shortfall";
            }
            else {chosen=choices.OrderByDescending(c=>Harness.DraftScore(c)).First();reason="Deterministic unknown choice fallback";}
            selected=new[]{chosen};
        }
        else if(number==57)
        {
            int s=player.Creature.GetPower<StrengthPower>()?.Amount??0;
            int f=DealLedger.Buff(player,49);
            int per=source!.DynamicVars["Effect"].IntValue;
            bool consume=per>=3+s+f && (player.Creature.GetPower<DealLedger>()?.Boasts.Stacks??0)==0;
            selected=consume?cards.Take(max):cards.Take(min);
            reason=consume?"Favor cash-out marginal damage exceeds individual play":"Preserve Favors for Strength scaling or active Boast";
        }
        else if(number is 18 or 32 or 41 or 71 || (number==63&&step>1) || (number==39&&step>1))
        {
            selected=cards.OrderByDescending(Value).Take(Math.Min(max,cards.Count));
            reason="Retain, recover, upgrade or make free highest policy-value cards";
        }
        else if(number is 2 or 13 or 20 or 23 or 29 or 37 or 38 or 39 or 45 or 47 or 59 or 63 or 64 or 65 or 69)
        {
            var expendable=cards.Where(c=>c.Type is CardType.Status or CardType.Curse || c is DealerStrike or DealerDefend).OrderBy(Value).ToList();
            if(expendable.Count<min)expendable.AddRange(cards.Except(expendable).OrderBy(Value).Take(min-expendable.Count));
            selected=expendable.Take(max);
            reason="Exhaust Statuses/curses first, then basic cards; preserve reward engines";
        }
        else
        {
            selected=cards.OrderByDescending(Value).Take(Math.Max(min,Math.Min(1,max)));
            reason="Unknown selection context: choose one highest-value card, respecting required count";
        }
        var result=selected.Take(max).ToArray();
        Harness.Log("selection",new{source=source?.Title,min,max,step,offered=cards.Select(Harness.Card).ToArray(),selected=result.Select(Harness.Card).ToArray(),reason});
        return result;
    }
}

[HarmonyPatch(typeof(AutoSlayCardSelector),nameof(AutoSlayCardSelector.GetSelectedCards))]
static class ContextualCardSelection
{
    static bool Prefix(IEnumerable<CardModel> options,int minSelect,int maxSelect,ref Task<IEnumerable<CardModel>> __result)
    {
        var cards=options.ToList();
        __result=DecisionBridge.Enabled ? RemotePilot.Select(cards,minSelect,maxSelect) : Task.FromResult(cards.Count==0?Enumerable.Empty<CardModel>():PolicySelections.Select(cards,minSelect,maxSelect));
        return false;
    }
}
