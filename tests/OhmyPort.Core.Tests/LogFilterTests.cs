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

    [Fact]
    public void RegexMode_MatchesByPattern()
    {
        var f = new LogFilter([@"\d{3,}"], FilterModes.Highlight, useRegex: true);
        Assert.Equal([@"\d{3,}"], f.Matched("err code=123"));
        Assert.Empty(f.Matched("err code=12"));
    }

    [Fact]
    public void RegexMode_RespectsCaseSensitivity()
    {
        var ci = new LogFilter(["error"], caseSensitive: false, useRegex: true);
        var cs = new LogFilter(["error"], caseSensitive: true, useRegex: true);
        Assert.Single(ci.Matched("ERROR: x"));
        Assert.Empty(cs.Matched("ERROR: x"));
    }

    [Fact]
    public void RegexMode_InvalidPatternIsIgnored()
    {
        var f = new LogFilter(["("], useRegex: true);
        Assert.Empty(f.Matched("anything"));
        Assert.True(f.Visible("anything"));
    }

    [Fact]
    public void RegexMode_VisibleAppliesIncludeExclude()
    {
        var include = new LogFilter(["^ERR"], FilterModes.Include, useRegex: true);
        var exclude = new LogFilter(["^ERR"], FilterModes.Exclude, useRegex: true);
        Assert.True(include.Visible("ERR: bad"));
        Assert.False(include.Visible("ok"));
        Assert.False(exclude.Visible("ERR: bad"));
        Assert.True(exclude.Visible("ok"));
    }
}
