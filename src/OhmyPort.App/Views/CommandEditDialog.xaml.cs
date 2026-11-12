using System.Windows;
using OhmyPort.Core.Models;

namespace OhmyPort.App.Views;

/// <summary>命令编辑对话框：名称 + 内容 + 所属页（添加与编辑共用）。</summary>
public partial class CommandEditDialog : Window
{
    private readonly IReadOnlyList<string> _pages;
    private readonly Func<int, int> _commandCountOfPage;

    public CommandEditDialog(IReadOnlyList<string> pages, Func<int, int> commandCountOfPage,
                             string title = "添加命令", string? name = null, string? content = null,
                             int page = 0, bool pageOnly = false)
    {
        InitializeComponent();
        _pages = pages;
        _commandCountOfPage = commandCountOfPage;

        Title = title;
        NameEdit.Text = name ?? "";
        ContentEdit.Text = content ?? "";
        PopulatePages(page);

        if (pageOnly)
        {
            ContentRow.Visibility = Visibility.Collapsed;
            PageRow.Visibility = Visibility.Collapsed;
        }

        OkButton.Click += (_, _) => DialogResult = true;
        CancelButton.Click += (_, _) => DialogResult = false;
        Loaded += (_, _) => NameEdit.Focus();
    }

    /// <summary>命令名称（重命名页等场景直接读写）。</summary>
    public string NameText
    {
        get => NameEdit.Text;
        set => NameEdit.Text = value;
    }

    public string CommandName => NameEdit.Text.Trim();

    public string CommandContent => ContentEdit.Text;

    /// <summary>选中的页索引；-1 表示新建页。</summary>
    public int SelectedPage => (PageCombo.SelectedItem as Option)?.Value as int? ?? -1;

    private void PopulatePages(int currentPage)
    {
        PageCombo.DisplayMemberPath = nameof(Option.Label);
        PageCombo.SelectedValuePath = nameof(Option.Value);

        var options = new List<Option>();
        var firstFree = -1;
        for (var i = 0; i < _pages.Count; i++)
        {
            var count = _commandCountOfPage(i);
            options.Add(new Option($"{_pages[i]}（{count}/8）", i));
            if (count < 8 && firstFree < 0)
            {
                firstFree = i;
            }
        }

        options.Add(new Option("（新建页）", -1));
        PageCombo.ItemsSource = options;

        // 编辑时优先选中原页；添加时选第一个未满页，全满则选「新建页」
        PageCombo.SelectedValue = currentPage >= 0 && currentPage < _pages.Count
            ? currentPage
            : firstFree >= 0 ? firstFree : -1;
    }
}
