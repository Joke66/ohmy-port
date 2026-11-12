using OhmyPort.Core.Models;
using Xunit;

namespace OhmyPort.Core.Tests;

public class PlotRuleTests
{
    [Fact]
    public void RegexRule_UsesFirstCaptureGroup()
    {
        var r = new PlotRule("temp", @"temp=(\d+\.?\d*)");
        Assert.Equal(36.5, r.Match("temp=36.5"));
        Assert.Null(r.Match("no"));
    }

    [Fact]
    public void KeywordRule_TakesFirstNumberAfterKeyword()
    {
        var r = new PlotRule("temp", "temp=");
        Assert.Equal(36.5, r.Match("temp=36.5"));
        Assert.Null(r.Match("humidity=40"));
    }

    [Fact]
    public void KeywordRule_IsCaseInsensitive()
    {
        var r = new PlotRule("temp", "TEMP=");
        Assert.Equal(12.0, r.Match("temp=12"));
    }

    [Fact]
    public void InvalidRegex_FallsBackToKeywordSearch()
    {
        var r = new PlotRule("bad", "temp=([0-9");
        Assert.Null(r.Match("temp=5"));
    }

    [Fact]
    public void RegexWithoutGroup_FallsBackToKeywordMode()
    {
        // 没有捕获组时不当作正则，按关键词处理
        var r = new PlotRule("v", @"voltage=\d+");
        Assert.Null(r.Match("voltage=5"));
        Assert.Equal(7.0, r.Match(@"x voltage=\d+ 7"));
    }
}
