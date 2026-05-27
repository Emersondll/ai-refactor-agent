# 🧠 PROJECT CONTEXT — AI REFACTOR AGENT (JAVA)

## 🎯 OBJECTIVE

Create an automated agent that:

* accesses repositories on GitHub
* identifies Java projects
* applies refactoring based on a central standard (`CLAUDE.md`)
* validates the build
* pushes changes automatically

---

## ⚙️ AGENT BEHAVIOR

On each execution:

```text
1. Fetches the user's repositories from GitHub
2. Filters candidates (Java language or name match)
3. Clones the repository into a temporary directory (/tmp)
4. Validates that it is a Java project (pom.xml or gradle)
5. Injects/updates CLAUDE.md (always overwrites)
6. Selects 1 .java file
7. Sends to the AI (Claude) for refactoring
8. Saves a backup (.bak)
9. Runs the build (Maven/Gradle)
10. On success:
    - controlled commit
    - push to branch ai/refactor
11. On failure:
    - rolls back the file
12. Marks the repo as processed
13. Processes only 1 repo per day
```

---

## 🧠 CENTRAL STANDARD

File:

```text
CLAUDE.md
```

Purpose:

* defines refactoring rules
* guides the AI
* is injected into all processed repositories

---

## 🔐 EXECUTION CONTROL

### Local files:

* `processed_repos.txt` → prevents reprocessing repos
* `last_run.txt` → limits execution to once per day

---

## 🛡️ SECURITY CONTROL

### Prevents:

* reprocessing
* infinite loop
* excessive API usage
* unnecessary commits
* inclusion of unintended files

### Strategies:

* isolated directory (`/tmp`)
* file size limit (~50KB)
* delay between executions
* controlled commit:

```bash
git add -u
git add CLAUDE.md
```

---

## ⚠️ RESOLVED CRITICAL ISSUES

### 1. Quota problem (OpenAI)

* replaced by Claude (Anthropic)

---

### 2. Risk of pushing unintended files

* removed `git add .`
* using `git add -u`

---

### 3. Infinite reprocessing

* resolved with state control (`processed_repos.txt`)

---

### 4. Excessive execution

* limited to **1 repository per day**

---

### 5. Lack of visibility

* added logs:

  * repos found
  * language detected
  * filter decisions

---

## 🔧 TECH STACK

* Python 3
* Git
* Maven / Gradle
* Anthropic API (Claude)
* GitHub API

---

## 🔑 CONFIGURATION (.env)

```env
ANTHROPIC_API_KEY=...
GITHUB_TOKEN=...
GITHUB_USERNAME=...
```

---

## 🚀 EXECUTION

```bash
source venv/bin/activate
python agent.py
```

---

## 📂 ISOLATION STRATEGY

* repos are cloned into `/tmp`
* removed at the end (or kept for debugging)
* avoids interference with the local project

---

## 🧠 CURRENT LIMITATIONS

* processes only 1 file per repo
* depends on Claude API credits
* depends on GitHub language detection
* does not create Pull Requests (direct push to branch)

---

## 🚀 POSSIBLE FUTURE IMPROVEMENTS

* automatic PR creation
* refactoring of multiple files
* diff analysis before commit
* fallback between AI providers
* automatic execution via cron
* cost control per execution

---

## 🎯 FINAL SUMMARY

This project is a:

```text
Autonomous Java refactoring agent guided by a central standard (CLAUDE.md),
with execution control, security, and AI integration.
```
