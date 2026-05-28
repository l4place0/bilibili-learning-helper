## ADDED Requirements

### Requirement: Thread-safe Whisper model access
系统 SHALL 使用锁保护 Whisper 全局状态，防止并发转录竞争。

#### Scenario: Concurrent transcriptions
- **WHEN** 两个任务同时调用 `transcribe()`
- **THEN** 模型加载和 OOM fallback 串行执行，不互相覆盖状态

#### Scenario: OOM during concurrent access
- **WHEN** 一个任务触发 CUDA OOM fallback，另一个任务同时运行
- **THEN** 两个任务都安全回退到 CPU，不出现 RuntimeError
