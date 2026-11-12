using OhmyPort.Core.Models;
using Xunit;

namespace OhmyPort.Core.Tests;

public class PlotHubTests
{
    [Fact]
    public void Series_KeepsOnlyCapacity_OldestDropped()
    {
        var s = new PlotSeries("v", 3);
        s.Add(1);
        s.Add(2);
        s.Add(3);
        s.Add(4);

        Assert.Equal(3, s.Count);
        Assert.Equal(2, s[0]);
        Assert.Equal(3, s[1]);
        Assert.Equal(4, s[2]);
    }

    [Fact]
    public void Series_Range_IgnoresNaN()
    {
        var s = new PlotSeries("v", 4);
        s.Add(double.NaN);
        s.Add(5);
        s.Add(1);
        s.Add(double.NaN);

        var range = s.Range();
        Assert.NotNull(range);
        Assert.Equal(1, range!.Value.Min);
        Assert.Equal(5, range.Value.Max);
        Assert.Equal(1, s.Latest);
    }

    [Fact]
    public void Series_EmptyRange_IsNull()
    {
        Assert.Null(new PlotSeries("v", 4).Range());
    }

    [Fact]
    public void Feed_ExtractsPerRule_AndRecordsNaNOnMiss()
    {
        var hub = new PlotHub();
        hub.Configure([new PlotRuleConfig("temp", "temp=")], 100);

        hub.Feed("temp=36.5");
        hub.Feed("no data");
        hub.Feed("temp=37");

        var s = hub.Series[0];
        Assert.Equal(3, s.Count);
        Assert.Equal(36.5, s[0]);
        Assert.True(double.IsNaN(s[1]));
        Assert.Equal(37, s[2]);
    }

    [Fact]
    public void Configure_KeepsSameNamedSeriesData()
    {
        var hub = new PlotHub();
        hub.Configure([new PlotRuleConfig("temp", "temp=")], 10);
        hub.Feed("temp=1");
        hub.Feed("temp=2");

        // 同名规则重配（只改规则文本）后数据保留
        hub.Configure([new PlotRuleConfig("temp", @"temp=(\d+)")], 10);
        Assert.Equal(2, hub.Series[0].Count);
        Assert.Equal(2, hub.Series[0][1]);
    }

    [Fact]
    public void Configure_DropsInvalidRules()
    {
        var hub = new PlotHub();
        hub.Configure(
        [
            new PlotRuleConfig("", "temp="),
            new PlotRuleConfig("湿度", ""),
            new PlotRuleConfig("电压", "v="),
        ], 10);

        Assert.Single(hub.Series);
        Assert.Equal("电压", hub.Series[0].Name);
        Assert.True(hub.Enabled);
    }

    [Fact]
    public void SetCapacity_RebuildsAndKeepsLatestPoints()
    {
        var hub = new PlotHub();
        hub.Configure([new PlotRuleConfig("v", "v=")], 10);
        for (var i = 0; i < 6; i++)
        {
            hub.Feed($"v={i}");
        }

        hub.SetCapacity(3);
        Assert.Equal(3, hub.Series[0].Count);
        Assert.Equal(3, hub.Series[0][0]);
        Assert.Equal(5, hub.Series[0][2]);
    }

    [Fact]
    public void Clear_EmptiesSeries()
    {
        var hub = new PlotHub();
        hub.Configure([new PlotRuleConfig("v", "v=")], 10);
        hub.Feed("v=1");
        hub.Clear();
        Assert.Equal(0, hub.Series[0].Count);
    }

    [Fact]
    public void NoRules_IsDisabledAndIgnoresFeed()
    {
        var hub = new PlotHub();
        Assert.False(hub.Enabled);
        hub.Feed("temp=1");   // 不应抛异常
        Assert.Empty(hub.Series);
    }
}
