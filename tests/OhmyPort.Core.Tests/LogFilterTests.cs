using OhmyPort.Core;
using Xunit;

namespace OhmyPort.Core.Tests;

public class LogFilterTests
{
    [Fact]
    public void ParseKeywords_SplitsOnCommaSemicolonWhitespace_AndDeduplicates()
    {
        Assert.Equal(["Err", "Timeout", "0x50"], LogFilter.ParseKeywords("Err,Timeout,0x50"));
        Assert.Equal(["a", "b", "c"], LogFilter.ParseKeywords("a  b c"));
        Assert.Equal(["a", "b"], LogFilter.ParseKeywords("a,a,b"));
        Assert.Empty(LogFilter.ParseKeywords(""));
        Assert.Empty(LogFilter.ParseKeywords(null));
    }

    [Fact]
    public void Matched_IsCaseInsensitiveByDefault()
    {
        var f = new LogFilter(["err"]);
        Assert.Equal(["err"], f.Matched("Error occurred"));
        Assert.Empty(f.Matched("no hit"));
    }

    [Fact]
    public void Matched_RespectsCaseSensitivity()
    {
        var f = new LogFilter(["err"], caseSensitive: true);
        Assert.Equal(["err"], f.Matched("err"));
        Assert.Empty(f.Matched("Error"));
    }

    [Fact]
    public void Visible_AppliesIncludeExcludeHighlightModes()
    {
        string[] kw = ["err"];
        var include = new LogFilter(kw, FilterModes.Include);
        var exclude = new LogFilter(kw, FilterModes.Exclude);
        var highlight = new LogFilter(kw, FilterModes.Highlight);

        Assert.True(include.Visible("Error"));
        Assert.False(include.Visible("ok"));
        Assert.False(exclude.Visible("Error"));
        Assert.True(exclude.Visible("ok"));
        Assert.True(highlight.Visible("anything"));
    }

    [Fact]
    public void Visible_WithNoKeywords_AlwaysTrue()
    {
        Assert.True(new LogFilter([], FilterModes.Include).Visible("anything"));
    }
}
