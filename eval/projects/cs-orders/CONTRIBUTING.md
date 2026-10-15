# Contributing

Build with `dotnet build -warnaserror` and run `dotnet test` before opening a pull request.

## Rules

- Async all the way: never block on a task with `.Result` or `.Wait()`.
- Log through `ILogger<T>`, never `Console.WriteLine`.
- Raw SQL only through `FromSql` with interpolated parameters, never `FromSqlRaw` with a built string.
- Controllers return `NotFound()` for a missing order, never `null`.
