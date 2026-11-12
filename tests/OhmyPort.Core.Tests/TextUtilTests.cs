using OhmyPort.Core;
using Xunit;

namespace OhmyPort.Core.Tests;

public class TextUtilTests
{
    [Fact]
    public void FormatValue_OmitsDecimalsForIntegers()
    {
        Assert.Equal("3", TextUtil.FormatValue(3.0));
        Assert.Equal("3.14", TextUtil.FormatValue(3.14));
        Assert.Equal("3.1416", TextUtil.FormatValue(3.14159));
        Assert.Equal("0", TextUtil.FormatValue(0.0));
        Assert.Equal("-1.5", TextUtil.FormatValue(-1.5));
    }

    [Fact]
    public void FormatBytes_UsesReadableUnits()
    {
        Assert.Equal("512 B", TextUtil.FormatBytes(512));
        Assert.Equal("2.0 KB", TextUtil.FormatBytes(2048));
        Assert.Equal("3.0 MB", TextUtil.FormatBytes(3 * 1024 * 1024));
    }

    [Fact]
    public void ExtractNumbers_FindsIntsDecimalsAndNegatives()
    {
        Assert.Equal([36.5], TextUtil.ExtractNumbers("temp=36.5"));
        Assert.Equal([1.0, 2.5, -3.0], TextUtil.ExtractNumbers("a1 b2.5 c-3"));
        Assert.Empty(TextUtil.ExtractNumbers("none"));
    }

    [Fact]
    public void ParseVersion_ExtractsTriplets()
    {
        Assert.Equal([1, 2, 0], TextUtil.ParseVersion("OhmyPort_v1.2.0"));
        Assert.Equal([1, 10, 0], TextUtil.ParseVersion("v1.10.0"));
        Assert.Empty(TextUtil.ParseVersion("no version"));
        Assert.Empty(TextUtil.ParseVersion(null));
    }

    [Fact]
    public void CompareVersions_OrdersNumerically()
    {
        Assert.True(TextUtil.CompareVersions([1, 10, 0], [1, 9, 9]) > 0);
        Assert.True(TextUtil.CompareVersions([1, 8, 7], [1, 8, 7]) == 0);
        Assert.True(TextUtil.CompareVersions([1, 8, 6], [1, 8, 7]) < 0);
    }
}
