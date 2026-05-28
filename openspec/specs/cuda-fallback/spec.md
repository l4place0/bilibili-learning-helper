## ADDED Requirements

### Requirement: Permanent CPU fallback on CUDA OOM
Whisper 转录 SHALL 在 CUDA OOM 时捕获异常，永久切换到 CPU 并重新加载模型重试。

#### Scenario: CUDA OOM during transcription
- **WHEN** Whisper 在 CUDA 上转录时抛出 out-of-memory 异常
- **THEN** 系统将设备缓存设为 "cpu"
- **AND** 清空模型缓存强制重新加载
- **AND** 在 CPU 上重新执行转录
- **AND** 后续调用直接使用 CPU（不再尝试 CUDA）

#### Scenario: CUDA works normally
- **WHEN** CUDA 可用且内存充足
- **THEN** 正常使用 GPU 推理，不触发回退

#### Scenario: CUDA not available
- **WHEN** 系统无 CUDA 设备
- **THEN** 直接使用 CPU，行为不变
