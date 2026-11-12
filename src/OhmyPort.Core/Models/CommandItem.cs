namespace OhmyPort.Core.Models;

/// <summary>发送辅助里的一个命令：名称 + 内容 + 是否参与定时循环 + 所属页。</summary>
public sealed class CommandItem
{
    public string Name { get; set; } = "";
    public string Content { get; set; } = "";
    public bool Cycle { get; set; }
    public int Page { get; set; }
}

/// <summary>
/// 命令页 / 命令的解析与校验（配置导入、导出、启动共用）。
/// 对应 Python 版 _load_pages_commands。
/// </summary>
public static class CommandPages
{
    /// <summary>
    /// 解析命令页与命令：无 pages 字段时保留默认页；页号越界或非法回退到第 1 页；
    /// 名称与内容都为空的命令丢弃。
    /// </summary>
    public static (List<string> Pages, List<CommandItem> Commands) Load(
        IReadOnlyList<string>? pages,
        IEnumerable<CommandItem?>? commands,
        IReadOnlyList<string> currentPages)
    {
        List<string> resultPages = pages is { Count: > 0 } ? [.. pages] : [.. currentPages];
        var resultCommands = new List<CommandItem>();

        foreach (var c in commands ?? [])
        {
            if (c is null || (c.Name.Length == 0 && c.Content.Length == 0))
            {
                continue;
            }

            var page = c.Page;
            if (page < 0 || page >= resultPages.Count)
            {
                page = 0;
            }

            resultCommands.Add(new CommandItem
            {
                Name = c.Name,
                Content = c.Content,
                Cycle = c.Cycle,
                Page = page,
            });
        }

        return (resultPages, resultCommands);
    }
}
