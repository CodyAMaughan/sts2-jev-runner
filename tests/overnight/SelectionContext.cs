using System.Reflection;
using HarmonyLib;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Commands;
namespace OvernightHarness;
[HarmonyPatch]
static class SelectionContext
{
    public static string Prompt="";
    static IEnumerable<MethodBase> TargetMethods()=>typeof(CardSelectCmd).GetMethods(BindingFlags.Static|BindingFlags.Public).Where(m=>m.GetParameters().Any(p=>p.ParameterType==typeof(CardSelectorPrefs)));
    static void Prefix(object[] __args){if(DecisionBridge.Enabled)Prompt=__args.OfType<CardSelectorPrefs>().First().Prompt.GetFormattedText();}
}
