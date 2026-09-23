using System.Net;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.AutoSlay;

namespace OvernightHarness;

// HTTP threads exchange immutable JSON and IDs only. Game objects stay on the Godot thread.
public static class DecisionBridge
{
    public static bool Enabled => Environment.GetEnvironmentVariable("DEALMAKER_REMOTE") == "1";
    static readonly object Gate = new();
    static string token = "";
    static string snapshot = "{\"status\":\"starting\"}";
    static long sequence;
    static volatile bool stopRequested;
    public static volatile bool ResetRequested;
    public static void ResetForReplay() {lock(Gate) {sequence=0;pending=null;pendingId=null;allowed.Clear();ResetRequested=false;stopRequested=false;snapshot="{\"status\":\"starting\"}";}}

    public static void SetPlaybackObservation(string json){lock(Gate)snapshot=json;}
    public static void SetTerminal(object outcome){lock(Gate)snapshot=JsonSerializer.Serialize(new {status="terminal",outcome});}
    public static bool HasPending { get { lock(Gate) return pending!=null; } }
    static string? pendingId;
    static HashSet<string> allowed = new();
    static TaskCompletionSource<string>? pending;
    public static void Start()
    {
        token = Environment.GetEnvironmentVariable("DEALMAKER_BRIDGE_TOKEN") ?? "";
        if (token.Length < 24) throw new InvalidOperationException("Bridge needs a random bearer token of at least 24 characters");
        int port = int.Parse(Environment.GetEnvironmentVariable("DEALMAKER_BRIDGE_PORT") ?? "18765");
        var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        _ = Task.Run(async () => { while(listener.IsListening) { var c=await listener.GetContextAsync(); _=Serve(c); } });
        Harness.Log("bridge_started",new {port,protocol=1});
    }
    static async Task Serve(HttpListenerContext c)
    {
        int code=200; string body;
        try {
            if(c.Request.Headers["Authorization"]!="Bearer "+token || c.Request.Headers["Origin"]!=null) { code=403;body="{\"error\":\"forbidden\"}"; }
            else if(c.Request.HttpMethod=="GET" && c.Request.Url!.AbsolutePath=="/state") { lock(Gate) body=snapshot; }
            else if(c.Request.HttpMethod=="POST" && c.Request.Url!.AbsolutePath=="/reset" && ReplaySession.Enabled) {
                lock(Gate) {
                    if(pending==null) {code=409;body="{\"error\":\"not_at_decision\"}";}
                    else {ResetRequested=true;pending.TrySetResult("__reset");pending=null;pendingId=null;snapshot="{\"status\":\"resetting\"}";body="{\"accepted\":true}";}
                }
            }
            else if(c.Request.HttpMethod=="POST" && c.Request.Url!.AbsolutePath=="/stop") {
                lock(Gate) {stopRequested=true;pending?.TrySetResult("__stop");pending=null;pendingId=null;snapshot="{\"status\":\"stopped\"}";}body="{\"accepted\":true}";
            }
            else if(c.Request.HttpMethod=="POST" && c.Request.Url!.AbsolutePath=="/action") {
                if(c.Request.ContentLength64<0 || c.Request.ContentLength64>4096) throw new InvalidDataException("Expected a small fixed-length JSON request");
                using var reader=new StreamReader(c.Request.InputStream);
                using var doc=JsonDocument.Parse(await reader.ReadToEndAsync().WaitAsync(TimeSpan.FromSeconds(5)));
                string id=doc.RootElement.GetProperty("decision_id").GetString()!, action=doc.RootElement.GetProperty("action_id").GetString()!;
                lock(Gate) {
                    if(id!=pendingId || pending==null) {code=409;body="{\"error\":\"stale_decision\"}";}
                    else if(!allowed.Contains(action)) {code=422;body="{\"error\":\"illegal_action\"}";}
                    else {var completion=pending;pending=null;pendingId=null;snapshot="{\"status\":\"busy\"}";body="{\"accepted\":true}";completion.TrySetResult(action);}
                }
            } else {code=404;body="{\"error\":\"not_found\"}";}
        } catch(Exception) {code=400;body="{\"error\":\"invalid_request\"}";}
        try {var bytes=Encoding.UTF8.GetBytes(body);c.Response.StatusCode=code;c.Response.ContentType="application/json";c.Response.ContentLength64=bytes.Length;await c.Response.OutputStream.WriteAsync(bytes);c.Response.Close();} catch(HttpListenerException) { }
    }
    public static async Task<int> Choose(string kind,object state,IReadOnlyList<object> options,CancellationToken ct)
    {
        if(stopRequested){Harness.Log("controller_stop",new {reason="Controller stopped between decisions"});MegaCrit.Sts2.Core.Nodes.NGame.Instance!.GetTree().Quit(0);throw new OperationCanceledException("Controller stopped");}
        if(options.Count==0) throw new InvalidOperationException("No legal options for "+kind);
        var id=(++sequence).ToString();
        var actions=options.Select((o,i)=>new {id="a"+i,option=o}).ToArray();
        var task=new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var observation=new {protocol=1,status="decision",decision_id=id,kind,state,actions};
        DecisionSnapshots.Capture(id,kind,observation);
        lock(Gate) {
            if(pending!=null)throw new InvalidOperationException("Overlapping decision requests");
            pendingId=id;allowed=actions.Select(a=>a.id).ToHashSet();pending=task;snapshot=JsonSerializer.Serialize(observation);
        }
        Harness.Log("remote_observation",observation);
        try {
            string action=await task.Task.WaitAsync(TimeSpan.FromMinutes(string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DEALMAKER_REPLAY_CONTROLS")) ? 4 : 240),ct);
            if(action=="__reset") throw new ReplayResetException();
            if(action=="__stop") {
                Harness.Log("controller_stop",new {reason="Controller requested stop; not a completed balance run"});
                MegaCrit.Sts2.Core.Nodes.NGame.Instance!.GetTree().Quit(0);
                throw new OperationCanceledException("Controller stopped");
            }
            AutoSlayer.CurrentWatchdog?.Reset("Remote decision "+id);
            Harness.Log("remote_action",new {decision_id=id,action_id=action});
            return int.Parse(action.AsSpan(1));
        } finally {lock(Gate) {if(pendingId==id){pendingId=null;pending=null;snapshot="{\"status\":\"stopped\"}";}}}
    }
}
