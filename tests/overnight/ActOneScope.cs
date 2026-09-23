using HarmonyLib;
using MegaCrit.Sts2.Core.Models;

namespace OvernightHarness;

// Scoped only to the explicitly requested Overgrowth benchmark.
[HarmonyPatch(typeof(ActModel),nameof(ActModel.GetRandomList))]
static class ActOneScope
{
    static void Postfix(ref IEnumerable<ActModel> __result)
    {
        if(Environment.GetEnvironmentVariable("DEALMAKER_ACT1_OVERGROWTH")=="1")
            __result=ActModel.GetDefaultList();
    }
}
