using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using OhmyPort.Core.Models;

namespace OhmyPort.App.Views;

/// <summary>
/// 命令页内容：把某页的命令渲染成 4 列按钮网格（每页最多 8 个）。
/// 按钮单击发送、右键编辑/删除（对应 Python 版 _rebuild_command_tabs + CommandButton）。
/// </summary>
public sealed class CommandPageContent : ContentControl
{
    public CommandPageContent(IReadOnlyList<CommandItem> commands, int page,
                              Action<int> send, Action<int> edit, Action<int> delete)
    {
        var grid = new Grid
        {
            Margin = new Thickness(4),
        };
        for (var i = 0; i < 4; i++)
        {
            grid.ColumnDefinitions.Add(new ColumnDefinition());
        }

        var column = 0;
        var row = 0;
        for (var index = 0; index < commands.Count; index++)
        {
            var cmd = commands[index];
            if (cmd.Page != page)
            {
                continue;
            }

            var button = new Button
            {
                Content = cmd.Name.Length > 0 ? cmd.Name : $"命令{index + 1}",
                Height = 34,
                MinWidth = 100,
                Margin = new Thickness(0, 0, 6, 6),
                HorizontalAlignment = HorizontalAlignment.Left,
                ToolTip = $"{cmd.Name}\n{cmd.Content}",
                Tag = index,
            };
            button.Click += (_, _) => send(index);
            button.ContextMenu = BuildCommandContextMenu(index, edit, delete);

            Grid.SetColumn(button, column);
            Grid.SetRow(button, row);
            grid.Children.Add(button);

            column++;
            if (column >= 4)
            {
                column = 0;
                row++;
            }
        }

        Content = grid;
    }

    private static ContextMenu BuildCommandContextMenu(int index, Action<int> edit, Action<int> delete)
    {
        var menu = new ContextMenu();
        var editItem = new MenuItem { Header = "编辑" };
        editItem.Click += (_, _) => edit(index);
        menu.Items.Add(editItem);

        var deleteItem = new MenuItem { Header = "删除" };
        deleteItem.Click += (_, _) => delete(index);
        menu.Items.Add(deleteItem);

        return menu;
    }
}
