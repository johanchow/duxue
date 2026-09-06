# DDD Skill 图形设计证据

- DDD Skill 将图作为关系复杂时的设计证据，而非装饰：Context Map 负责业务边界和集成所有权；Layered Architecture Map 负责代码/运行时依赖，二者不能混成一张全景图。
- Context 内使用 Aggregate Map 描述多个写聚合和一致性边界；仅在内部实体/值对象关系不直观时使用 Aggregate Internal UML。
- State Diagram、Command–Event–Projection Flow、Event Choreography 和 Request Sequence Diagram 均按生命周期、最终一致性、跨 Context 与异步交互的实际复杂度触发。
