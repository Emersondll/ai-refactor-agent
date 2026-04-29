# Phase 10 — Clean Code

Apply Clean Code rules. You MUST make concrete code changes.

## What you MUST do

### Dead code
- Remove every unused local variable.
- Remove every commented-out code block (old implementations in `//` comments).
- Replace empty catch blocks `catch (Exception e) {}` with at minimum:
  `log.warn("Description of what failed", e);`

### Magic values
- Replace every magic number with a named constant.
  `if (code == 51)` → `private static final String INSUFFICIENT_FUNDS = "51"; ... if (code.equals(INSUFFICIENT_FUNDS))`
- Replace every magic string used more than once with a named constant.

### Method size
- Split every method longer than 20 lines into smaller private methods.
- Each extracted method must have a single clear responsibility and a descriptive name.

### Naming
- Replace single-letter variable names (`e`, `x`, `m`, `s`, `o`) with descriptive names,
  except for standard loop indices (`i`, `j`) and short lambda parameters.

### Exception handling
- Replace `catch (Exception e)` with the most specific exception type known.
- Every catch block must either log the error or rethrow — never swallow silently.

Do not change method signatures, return types, or public API.