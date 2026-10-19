# 📈 Evaluation & Fidelity Benchmark Report

## Overall Conversion Fidelity
| Sample | Structure | Expression | Behaviour | Coverage | Unsup. | Warn. | Fidelity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `01_leave_approval` | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | **100.0%** |
| `02_simple_email` | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | **100.0%** |
| `03_set_variable` | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | **100.0%** |
| `04_unsupported_loop` | 100.0% | 100.0% | 100.0% | 66.67% | 1 | 0 | **93.3%** |
| `05_nested_conditions` | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | **100.0%** |
| `06_variable_in_condition` | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 0 | **100.0%** |
| `07_bad_reference` | 100.0% | 100.0% | 100.0% | 100.0% | 0 | 1 | **95.0%** |
| `08_multiple_unsupported` | 100.0% | 100.0% | 100.0% | 60.0% | 2 | 0 | **92.0%** |

### 🧮 Scoring Formula
- **Overall Fidelity** = `0.25 * Structure + 0.25 * Expression + 0.30 * Behaviour + 0.20 * Coverage - (5 * Warnings)`
- **Structure Score**: Validates trigger and action types sequence against reference.
- **Expression Score**: Matches parameter expression conversions against ground truth.
- **Behaviour Score**: Verifies simulation traces match across Nintex and Power Automate execution.
- **Coverage %**: Percentage of workflow actions mapped without fallback.
- **Warning Penalty**: Each warning reduces fidelity score by 5 points.
