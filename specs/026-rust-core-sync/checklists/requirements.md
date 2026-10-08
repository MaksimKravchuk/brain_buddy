# Specification Quality Checklist: Rust core и sync

**Purpose**: проверка полноты спецификации до утверждения реализации.
**Created**: 2026-10-08. **Feature**: [spec.md](../spec.md).

## Содержание

- [x] Описаны проблема, пользователь, ценность, scope и non-goals.
- [x] User stories независимы по проверяемому результату; Given/When/Then включают отказ и восстановление.
- [x] В spec поведение отделено от реализации в plan/contract; Rust является явным ограничением пользователя.
- [x] FR и SC проверяемы; предложенные числовые бюджеты не выданы за измеренный результат.
- [x] Есть consent/local-first, mobile, observability и data-loss требования.
- [x] Не переписаны accepted Task/Review/Identity/CRT/A2A контракты без обозначенного ADR proposal.
- [x] Правила конфликтов, lost ACK, reset, retention, compatibility и migration описаны.
- [x] Платформенные тесты не объявлены ненужными из-за общего Rust-кода.
- [x] Допущения и неподтверждённые решения явно перечислены.

## Готовность к реализации

- [ ] Получен human sign-off новых conflict/recovery screens в design.md.
- [ ] Proposed ADR и defaults (limits, retention, compatibility, cohort/platform order) приняты в contract slice.
- [ ] Выполнен официальный planning review с допустимым verdict и актуальным digest.
- [ ] Согласована подробная PR-slice map и выполнен analyze перед coding.

Отсутствие этих approvals не мешает закончить запрошенную спецификацию как Draft, но не позволяет выдать её за допуск к реализации. Проверки документа и независимые замечания записаны в [verification.md](../verification.md).
