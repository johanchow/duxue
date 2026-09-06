# DDD 聚合内部模型产物

- DDD 技能将 Entity Inventory 与 Aggregate Internal UML 设为非简单 Aggregate 的必需产物：只要 Aggregate 拥有 Child Entity，或不变量依赖内部对象关系，就必须同时给出两者。
- Inventory 记录的是影响领域判断、生命周期或不变量的 Identity、关键属性、领域行为与责任边界；它不是 ORM/DTO/数据库字段清单。
- `design-memory.md` 对 `EpisodicMemory` 与 `DerivedSignal` 补充了该产物。两者均以 ID 引用 Evidence Ledger 的 `LearningEvent`，不把它误画成聚合内部 Entity。
