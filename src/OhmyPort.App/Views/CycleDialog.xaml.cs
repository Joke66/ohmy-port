using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using OhmyPort.Core.Models;

namespace OhmyPort.App.Views;

/// <summary>定时循环发送设置：启用/间隔/勾选参与循环的命令（对应 Python 版 CycleDialog）。</summary>
public partial class CycleDialog : Window
{
    private readonly Action<bool> _onEnableChanged;
    private readonly Action<int> _onIntervalChanged;
    private readonly Action<int, bool> _onCommandCycleChanged;
    private bool _suppress = true;

    public CycleDialog(bool enabled, int interval, IReadOnlyList<CommandItem> commands,
                       Action<bool> onEnableChanged, Action<int> onIntervalChanged,
                       Action<int, bool> onCommandCycleChanged)
    {
        InitializeComponent();
        _onEnableChanged = onEnableChanged;
        _onIntervalChanged = onIntervalChanged;
        _onCommandCycleChanged = onCommandCycleChanged;

        EnableCheck.IsChecked = enabled;
        IntervalEdit.Text = interval.ToString();

        EnableCheck.Click += (_, _) => _onEnableChanged(EnableCheck.IsChecked == true);
        IntervalEdit.TextChanged += OnIntervalTextChanged;

        CommandList.ItemsSource = commands
            .Select((c, i) => new CycleItem(c.Name.Length > 0 ? c.Name : $"命令{i + 1}", c.Content, c.Cycle))
            .ToList();

        foreach (var item in CommandList.ItemsSource)
        {
            ((CycleItem)item).PropertyChanged += OnItemPropertyChanged;
        }

        _suppress = false;
    }

    public void Refresh(bool enabled, int interval, IReadOnlyList<CommandItem> commands)
    {
        _suppress = true;
        EnableCheck.IsChecked = enabled;
        if (!IntervalEdit.IsFocused)
        {
            IntervalEdit.Text = interval.ToString();
        }

        CommandList.ItemsSource = commands
            .Select((c, i) => new CycleItem(c.Name.Length > 0 ? c.Name : $"命令{i + 1}", c.Content, c.Cycle))
            .ToList();

        foreach (var item in CommandList.ItemsSource)
        {
            ((CycleItem)item).PropertyChanged += OnItemPropertyChanged;
        }

        _suppress = false;
    }

    private void OnIntervalTextChanged(object sender, TextChangedEventArgs e)
    {
        if (_suppress)
        {
            return;
        }

        if (int.TryParse(IntervalEdit.Text, out var ms))
        {
            _onIntervalChanged(Math.Clamp(ms, 10, 3_600_000));
        }
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (_suppress || sender is not CycleItem item)
        {
            return;
        }

        var items = CommandList.ItemsSource as IReadOnlyList<CycleItem>;
        var index = items is null ? -1 : IndexOf(items, item);
        if (index >= 0)
        {
            _onCommandCycleChanged(index, item.IsChecked);
        }
    }

    private static int IndexOf(IReadOnlyList<CycleItem> items, CycleItem target)
    {
        for (var i = 0; i < items.Count; i++)
        {
            if (ReferenceEquals(items[i], target))
            {
                return i;
            }
        }

        return -1;
    }

    protected override void OnClosed(EventArgs e)
    {
        // 关闭对话框不停止循环（与 Python 版一致，循环状态独立于弹窗）
        base.OnClosed(e);
    }
}

/// <summary>循环命令列表项。</summary>
public sealed class CycleItem : INotifyPropertyChanged
{
    private bool _isChecked;

    public CycleItem(string label, string content, bool isChecked)
    {
        Label = label;
        Content = content;
        _isChecked = isChecked;
    }

    public string Label { get; }
    public string Content { get; }

    public bool IsChecked
    {
        get => _isChecked;
        set
        {
            if (_isChecked != value)
            {
                _isChecked = value;
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsChecked)));
            }
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
}
