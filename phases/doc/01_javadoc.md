# Phase 01 — Javadoc

Add Javadoc to every public element that does not already have it.

## What you MUST do

- Add a class-level Javadoc with a one-sentence description of the class responsibility.
- Add a Javadoc block to every public method without one. Include:
  - One-sentence summary of what the method does.
  - `@param` for every parameter.
  - `@return` if return type is not void.
  - `@throws` for every checked exception in the signature.
- Do not touch private or package-private methods.
- Do not alter existing code — only add comments.