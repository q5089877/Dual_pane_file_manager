using System;
using System.IO;
using System.Threading;
using DFE.Indexer.Models;

namespace DFE.Indexer.Services;

/// <summary>
/// Wraps FileSystemWatcher and writes incremental changes to SQLite.
/// A 500 ms debounce timer batches rapid bursts before sending the UDP notification.
/// </summary>
public sealed class FileWatcher : IDisposable
{
    private readonly SqliteIndexWriter _writer;
    private readonly UdpNotifier _notifier;
    private readonly FileSystemWatcher _fsw;
    private readonly Timer _debounce;
    private int _pendingCount;
    private readonly object _lock = new();

    private static readonly HashSet<string> ExcludedExts = new(StringComparer.OrdinalIgnoreCase)
    {
        ".tmp", ".bak", ".log", ".cache", ".db-wal", ".db-shm", ".lock",
    };

    public FileWatcher(string rootPath, SqliteIndexWriter writer, UdpNotifier notifier)
    {
        _writer   = writer;
        _notifier = notifier;
        _debounce = new Timer(OnDebounceElapsed, null, Timeout.Infinite, Timeout.Infinite);

        _fsw = new FileSystemWatcher(rootPath)
        {
            IncludeSubdirectories = true,
            NotifyFilter = NotifyFilters.FileName
                         | NotifyFilters.LastWrite
                         | NotifyFilters.DirectoryName
                         | NotifyFilters.Size,
            // Increase internal buffer (default 8 KB, max 64 KB) to handle burst events
            InternalBufferSize = 65536,
            EnableRaisingEvents = true,
        };

        _fsw.Created += OnCreated;
        _fsw.Deleted += OnDeleted;
        _fsw.Renamed += OnRenamed;
        _fsw.Changed += OnChanged;
        _fsw.Error   += OnError;
    }

    // ── Event handlers ───────────────────────────────────────────────────────

    private void OnCreated(object _, FileSystemEventArgs e)
    {
        if (ShouldSkip(e.FullPath)) return;
        try
        {
            var info = new FileInfo(e.FullPath);
            if (!info.Exists) return;
            double mtime = ((DateTimeOffset)info.LastWriteTimeUtc).ToUnixTimeSeconds();
            _writer.UpsertFileSingle(new FileRecord(info.DirectoryName ?? string.Empty, info.Name, mtime, info.Length));
            ReportChange();
        }
        catch { /* file may have been deleted between events */ }
    }

    private void OnDeleted(object _, FileSystemEventArgs e)
    {
        if (ShouldSkip(e.FullPath)) return;
        _writer.DeleteFile(Path.GetDirectoryName(e.FullPath) ?? string.Empty, Path.GetFileName(e.FullPath));
        ReportChange();
    }

    private void OnRenamed(object _, RenamedEventArgs e)
    {
        if (ShouldSkip(e.FullPath)) return;
        string folder    = Path.GetDirectoryName(e.FullPath) ?? string.Empty;
        string oldFolder = Path.GetDirectoryName(e.OldFullPath) ?? string.Empty;

        if (string.Equals(folder, oldFolder, StringComparison.OrdinalIgnoreCase))
        {
            // Same folder — simple rename
            _writer.RenameFile(folder, Path.GetFileName(e.OldFullPath), Path.GetFileName(e.FullPath));
        }
        else
        {
            // Moved to different folder — delete old, insert new
            _writer.DeleteFile(oldFolder, Path.GetFileName(e.OldFullPath));
            try
            {
                var info = new FileInfo(e.FullPath);
                if (info.Exists)
                {
                    double mtime = ((DateTimeOffset)info.LastWriteTimeUtc).ToUnixTimeSeconds();
                    _writer.UpsertFileSingle(new FileRecord(folder, info.Name, mtime, info.Length));
                }
            }
            catch { }
        }
        ReportChange();
    }

    private void OnChanged(object _, FileSystemEventArgs e)
    {
        if (ShouldSkip(e.FullPath)) return;
        try
        {
            var info = new FileInfo(e.FullPath);
            if (!info.Exists) return;
            double mtime = ((DateTimeOffset)info.LastWriteTimeUtc).ToUnixTimeSeconds();
            _writer.UpsertFileSingle(new FileRecord(info.DirectoryName ?? string.Empty, info.Name, mtime, info.Length));
            ReportChange();
        }
        catch { }
    }

    private void OnError(object _, ErrorEventArgs e)
    {
        Console.Error.WriteLine($"[FileWatcher] Error: {e.GetException().Message}");
        // Re-enable after overflow — events may have been lost
        try { _fsw.EnableRaisingEvents = true; } catch { }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private static bool ShouldSkip(string fullPath)
    {
        string ext = Path.GetExtension(fullPath);
        return ExcludedExts.Contains(ext);
    }

    private void ReportChange()
    {
        lock (_lock) { _pendingCount++; }
        // Reset debounce: fire 500 ms after the last event in a burst
        _debounce.Change(500, Timeout.Infinite);
    }

    private void OnDebounceElapsed(object? _)
    {
        int count;
        lock (_lock) { count = _pendingCount; _pendingCount = 0; }
        if (count > 0) _notifier.Send(count);
    }

    public void Dispose()
    {
        _debounce.Dispose();
        _fsw.Dispose();
    }
}
