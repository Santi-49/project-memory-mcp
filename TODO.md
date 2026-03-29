# TODO:

- Add version control (with git)
  - Before any write operation require the model to start a transaction with a commit message
  - all changes after that are linked to the same transaction
  - If the finish_transaction (with an optional parameter to overwrite the commit message) tool is called or a set time has passed commit
  - If accidentally overwriten info or made a big error model can rollback the transaction
  - Easy to track project knowledge versions
- Add rag capabilities:
  - All files are indexed using a local rag sistem
  - if a file is modified it should also re index it
  - Handle casuistic where files can be manually modified (check last modified and las indexed)
  - Expose a tool to search files based on semantic meaning (parameters like project slug...)
- Add auth to allow exposure to the internet
