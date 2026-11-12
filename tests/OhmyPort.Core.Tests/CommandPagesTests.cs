using OhmyPort.Core.Models;
using Xunit;

namespace OhmyPort.Core.Tests;

public class CommandPagesTests
{
    private static readonly List<string> DefaultPages = ["第1页"];

    [Fact]
    public void Load_RoundTripsPagesAndCommands()
    {
        List<string> pages = ["第1页", "测控", "调试"];
        List<CommandItem> commands =
        [
            new() { Name = "查询温度", Content = "AA 55 01", Cycle = true, Page = 1 },
            new() { Name = "重启", Content = "AA 55 02", Cycle = false, Page = 2 },
        ];

        var (outPages, outCommands) = CommandPages.Load(pages, commands, DefaultPages);

        Assert.Equal(pages, outPages);
        Assert.Equal(2, outCommands.Count);
        Assert.Equal("查询温度", outCommands[0].Name);
        Assert.Equal("AA 55 01", outCommands[0].Content);
        Assert.True(outCommands[0].Cycle);
        Assert.Equal(1, outCommands[0].Page);
        Assert.Equal(2, outCommands[1].Page);
    }

    [Fact]
    public void Load_OutOfRangePage_FallsBackToFirstPage()
    {
        var (pages, commands) = CommandPages.Load(
            ["第1页"],
            [new CommandItem { Name = "x", Content = "y", Page = 99 }],
            DefaultPages);

        Assert.Equal(["第1页"], pages);
        Assert.Equal(0, commands[0].Page);
    }

    [Fact]
    public void Load_NegativePage_FallsBackToFirstPage()
    {
        var (_, commands) = CommandPages.Load(
            null,
            [new CommandItem { Name = "x", Content = "y", Page = -3 }],
            DefaultPages);

        Assert.Equal(0, commands[0].Page);
    }

    [Fact]
    public void Load_MissingPages_KeepsCurrentPages()
    {
        var (pages, commands) = CommandPages.Load(
            null,
            [new CommandItem { Name = "x", Content = "y", Page = 0 }],
            DefaultPages);

        Assert.Equal(DefaultPages, pages);
        Assert.Equal(0, commands[0].Page);
    }

    [Fact]
    public void Load_SkipsCommandsWithNoNameAndNoContent()
    {
        var (_, commands) = CommandPages.Load(
            ["第1页"],
            [new CommandItem { Name = "", Content = "", Page = 0 },
             new CommandItem { Name = "ok", Content = "1", Page = 0 }],
            DefaultPages);

        Assert.Single(commands);
        Assert.Equal("ok", commands[0].Name);
    }
}
