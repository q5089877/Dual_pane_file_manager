using System.IO;
using DFE.Indexer.Models;

namespace DFE.Indexer.Services;

public static class DirectoryScanner
{
    private static readonly HashSet<string> ExcludedDirs = new(StringComparer.OrdinalIgnoreCase)
    {
        ".git", ".svn",
        "node_modules", "bower_components", ".next", ".nuxt",
        "__pycache__", "venv", ".venv", ".tox", ".pytest_cache", ".mypy_cache",
        "bin", "obj", ".vs", "packages",
        "build", "dist", "out", "target", "debug", "release",
        ".idea", ".vscode",
        "cache", "caches", "appdata", "crashreports",
        "windows", "program files", "program files (x86)", "programdata",
        "$recycle.bin", "system volume information",
    };

    private static readonly HashSet<string> ExcludedExts = new(StringComparer.OrdinalIgnoreCase)
    {
        ".tmp", ".bak", ".log", ".cache",
        ".db-wal", ".db-shm", ".lock",
        ".thumbs",
    };

    public static IEnumerable<FileRecord> Scan(string rootPath)
    {
        var options = new EnumerationOptions
        {
            IgnoreInaccessible = true,        // skip unauthorized folders at the OS level
            RecurseSubdirectories = true,
            ReturnSpecialDirectories = false,
            AttributesToSkip = FileAttributes.System | FileAttributes.ReparsePoint,
        };

        foreach (var file in new DirectoryInfo(rootPath).EnumerateFiles("*", options))
        {
            if (ExcludedExts.Contains(file.Extension))
                continue;

            if (IsInExcludedDir(file.DirectoryName, rootPath))
                continue;

            double mtime = ((DateTimeOffset)file.LastWriteTimeUtc).ToUnixTimeSeconds();
            yield return new FileRecord(file.DirectoryName ?? rootPath, file.Name, mtime, file.Length);
        }
    }

    private static bool IsInExcludedDir(string? directoryName, string rootPath)
    {
        if (directoryName is null) return false;

        // Only check path segments that are below rootPath
        ReadOnlySpan<char> relative = directoryName.AsSpan();
        ReadOnlySpan<char> root = rootPath.AsSpan();
        if (relative.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            relative = relative[root.Length..].TrimStart(Path.DirectorySeparatorChar);

        // Walk each segment of the relative path
        while (!relative.IsEmpty)
        {
            int sep = relative.IndexOf(Path.DirectorySeparatorChar);
            ReadOnlySpan<char> segment = sep < 0 ? relative : relative[..sep];

            if (ExcludedDirs.Contains(segment.ToString()))
                return true;

            if (sep < 0) break;
            relative = relative[(sep + 1)..];
        }

        return false;
    }
}
