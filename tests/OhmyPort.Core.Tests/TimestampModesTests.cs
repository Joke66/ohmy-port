using OhmyPort.Core;
using Xunit;

namespace OhmyPort.Core.Tests;

public class TimestampModesTests
{
    [Fact]
    public void Format_ProducesExpectedPrecision()
    {
        var t = new DateTime(2026, 11, 12, 9, 8, 7, 123);

        Assert.Equal("09:08:07.123", TimestampModes.Format(t, TimestampModes.Full));
        Assert.Equal("09:08:07", TimestampModes.Format(t, TimestampModes.Seconds));
        Assert.Equal("", TimestampModes.Format(t, TimestampModes.Off));
    }
}
