# TODO:

- Add version control (with git)
  - Before any write operation require the model to start a transaction with a commit message
  - all changes after that are linked to the same transaction
  - If the finish_transaction (with an optional parameter to overwrite the commit message) tool is called or a set time has passed commit
  - If accidentally overwriten info or made a big error model can rollback the transaction
  - Easy to track project knowledge versions
- Add linear and jira integrations