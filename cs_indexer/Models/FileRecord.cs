namespace DFE.Indexer.Models;

public sealed record FileRecord(
    string FolderPath,
    string Name,
    double Mtime,     // Unix timestamp (seconds)
    long Size         // bytes
);
