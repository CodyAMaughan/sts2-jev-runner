using Godot;
using Environment = System.Environment;
using System.Text.Json;
namespace OvernightHarness;

// This UI exists only in the disposable replay process.
public class ReplayOverlay
{
    string directory="";Label info=new();Button play=new();SpinBox destination=new();bool playing;
    public static void Attach()
    {
        var path=Environment.GetEnvironmentVariable("DEALMAKER_REPLAY_CONTROLS");
        if(string.IsNullOrEmpty(path))return;
        // Plain mod assemblies do not run Godot's script source generator.
        // Build native nodes explicitly instead of relying on _Ready/_Process
        // overrides which Godot cannot dispatch for this unregistered script.
        Callable.From(()=>new ReplayOverlay{directory=path}.Build()).CallDeferred();
    }
    void Send(string action,object? extra=null)
    {
        var command=new Dictionary<string,object?>{["action"]=action,["nonce"]=Guid.NewGuid().ToString()};
        if(action=="rate")command["seconds"]=extra;if(action=="seek")command["index"]=extra;
        var path=Path.Combine(directory,"command.json");File.WriteAllText(path+".tmp",JsonSerializer.Serialize(command));File.Move(path+".tmp",path,true);
    }
    void Build()
    {
        var layer=new CanvasLayer{Layer=120,Name="DealmakerReplayControls"};
        var panel=new PanelContainer{Position=new Vector2(220,8)};
        panel.AddThemeStyleboxOverride("panel",new StyleBoxFlat{BgColor=new Color(.07f,.08f,.1f,.97f),ContentMarginLeft=12,ContentMarginRight=12,ContentMarginTop=8,ContentMarginBottom=8});
        var column=new VBoxContainer();panel.AddChild(column);info.Text="Recorded replay — loading";column.AddChild(info);
        var row=new HBoxContainer();column.AddChild(row);
        Button Add(string text,Action action){var b=new Button{Text=text};b.Pressed+=action;row.AddChild(b);return b;}
        Add("Back",()=>Send("back"));play=Add("Play",()=>Send(playing?"pause":"play"));Add("Step",()=>Send("step"));
        var rate=new OptionButton();foreach(var label in new[]{"0 s","0.25 s","1 s","2 s","5 s"})rate.AddItem(label);
        rate.Selected=2;rate.ItemSelected+=i=>Send("rate",new[]{0d,.25d,1d,2d,5d}[(int)i]);row.AddChild(rate);
        destination.MinValue=1;destination.MaxValue=10000;destination.Value=1;row.AddChild(destination);Add("Go to move",()=>Send("seek",(int)destination.Value-1));
        Add("Close replay",()=>Send("stop"));
        var note=new Label{Text=SnapshotPlayback.Enabled?"Direct snapshots. No model calls.":"Legacy reconstruction. No model calls."};note.AddThemeFontSizeOverride("font_size",14);column.AddChild(note);layer.AddChild(panel);
        var timer=new Godot.Timer{WaitTime=.2,Autostart=true};timer.Timeout+=()=>Tick();layer.AddChild(timer);
        ((SceneTree)Engine.GetMainLoop()).Root.AddChild(layer);
        Harness.Log("replay_overlay_ready",new{controls=new[]{"Back","Play/Pause","Step","Rate","Go to move"},mechanism="native nodes and timer signals"});
    }
    void Tick()
    {
        try{
            using var doc=JsonDocument.Parse(File.ReadAllText(Path.Combine(directory,"status.json")));var s=doc.RootElement;
            int current=s.GetProperty("index").GetInt32(),total=s.GetProperty("total").GetInt32();string mode=s.GetProperty("mode").GetString()!;playing=mode=="Playing";
            info.Text=$"REPLAY | Move {current+1}/{total} | {mode}";play.Text=playing?"Pause":"Play";destination.MaxValue=total;
            MegaCrit.Sts2.Core.AutoSlay.AutoSlayer.CurrentWatchdog?.Reset("Replay controls");
        }catch(Exception){}
    }
}
