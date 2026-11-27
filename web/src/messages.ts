// The page's text, in one place so a second language is one more file.
export const messages = {
  addFailed: "Cannot add the category",
  answered: (account: string) => `Answered: ${account}`,
  choicesDiffer: "Choices differ",
  create: (account: string) => `New category: ${account}`,
  doneTitle: "All cards seen",
  doneText: (rows: number) =>
    `${rows} rows answered in this session. A rebuild of the ledger books them.`,
  emptyTitle: "Nothing to review",
  emptyText: "No open row has a cached suggestion. Run categorize first.",
  keys: {
    pick: "pick",
    search: "search",
    skip: "skip",
    split: "one by one",
    undo: "back",
  },
  loadFailed: "Cannot load the review",
  more: (n: number) => `and ${n} more`,
  nothingFound: "No category matches",
  progress: (answered: number, skipped: number, left: number, total: number) =>
    `${answered} answered · ${skipped} skipped · ${left} left of ${total} rows`,
  rowChoice: (percent: number) => `Top choice for this row (${percent}%):`,
  rows: (n: number) => (n === 1 ? "1 row" : `${n} rows`),
  saveFailed: "Cannot save the answer",
  searchPlaceholder: "Search or add a category… Tab completes a level",
  skipped: "Skipped",
  sure: "Sure",
  title: (year: number | null) => (year ? `Category review ${year}` : "Category review"),
  upNext: "Up next",
};
