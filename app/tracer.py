import os
import sys
from datetime import datetime
from typing import Any, Optional
from contextvars import ContextVar
from functools import wraps

_trace_depth: ContextVar[int] = ContextVar('trace_depth', default=0)
TRACING_ENABLED = os.getenv('ENABLE_TRACING', 'true').lower() in ('true', '1', 'yes')

class Tracer:    
    @staticmethod
    def _get_timestamp() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
    @staticmethod
    def _get_indent() -> str:
        depth = _trace_depth.get()
        if depth == 0:
            return ''
        return '  ' * depth
    
    @staticmethod
    def _format_value(value: Any, max_length: int = 100, key: str = '') -> str:
        str_value = str(value)
        if key in ('response', 'prompt'):
            lines = str_value.split('\n')
            if len(lines) > 5:
                seen_lines = {}
                line_order = []
                for line in lines:
                    stripped = line.strip()
                    if stripped:
                        if stripped not in seen_lines:
                            seen_lines[stripped] = 0
                            line_order.append(stripped)
                        seen_lines[stripped] += 1
                if any(count > 1 for count in seen_lines.values()):
                    result_lines = []
                    for stripped in line_order:
                        count = seen_lines[stripped]
                        if count > 1:
                            result_lines.append(f"{stripped} [repeated {count}x]")
                        else:
                            result_lines.append(stripped)
                    return '\n'.join(result_lines)
            return str_value
        
        if len(str_value) > max_length:
            return str_value[:max_length] + '...'
        return str_value
    
    @staticmethod
    def trace(event_type: str, message: str, **details: Any) -> None:
        if not TRACING_ENABLED:
            return
        timestamp = Tracer._get_timestamp()
        indent = Tracer._get_indent()
        
        print(f"{indent}[{timestamp}] {message}", file=sys.stderr)
        if details:
            detail_indent = indent + '  '
            for i, (key, value) in enumerate(details.items()):
                is_last = i == len(details) - 1
                prefix = '└─' if is_last else '├─'
                formatted_value = Tracer._format_value(value, key=key)
                print(f"{detail_indent}{prefix} {key}: {formatted_value}", file=sys.stderr)
    
    @staticmethod
    def trace_start(event_type: str, message: str, **details: Any) -> None:
        if not TRACING_ENABLED:
            return
        
        Tracer.trace(event_type, message, **details)
        _trace_depth.set(_trace_depth.get() + 1)
    
    @staticmethod
    def trace_end(event_type: str, message: str, **details: Any) -> None:
        if not TRACING_ENABLED:
            return  
        current_depth = _trace_depth.get()
        if current_depth > 0:
            _trace_depth.set(current_depth - 1)
        Tracer.trace(event_type, message, **details)
    
    @staticmethod
    def trace_context(event_type: str, message: str, **details: Any):
        return _TraceContext(event_type, message, details)

class _TraceContext:
    def __init__(self, event_type: str, message: str, details: dict):
        self.event_type = event_type
        self.message = message
        self.details = details
        self.start_time: Optional[datetime] = None
    
    def __enter__(self):
        if TRACING_ENABLED:
            self.start_time = datetime.now()
            Tracer.trace_start(self.event_type, f"{self.message} (START)", **self.details)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if TRACING_ENABLED:
            if exc_type is not None:
                Tracer.trace_end('error', f"{self.message} (ERROR)",
                               error=f"{exc_type.__name__}: {exc_val}")
            else:
                if self.start_time is not None:
                    elapsed = (datetime.now() - self.start_time).total_seconds()
                    Tracer.trace_end('complete', f"{self.message} (COMPLETE)",
                                   elapsed_seconds=f"{elapsed:.3f}")
        return False

def trace_function(event_type: str = 'info', message: Optional[str] = None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not TRACING_ENABLED:
                return func(*args, **kwargs)
            
            func_message = message or f"{func.__name__}()"
            with Tracer.trace_context(event_type, func_message):
                return func(*args, **kwargs)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not TRACING_ENABLED:
                return await func(*args, **kwargs)
            
            func_message = message or f"{func.__name__}()"
            with Tracer.trace_context(event_type, func_message):
                return await func(*args, **kwargs)
        return wrapper
    return decorator

def trace_agent_start(task_id: str, context_id: str, query: str) -> None:
    Tracer.trace_start('start', 'AGENT_EXECUTOR_START',
                      task_id=task_id, context_id=context_id, query=query)

def trace_agent_end(task_id: str, status: str) -> None:
    Tracer.trace_end('complete', 'AGENT_EXECUTOR_COMPLETE',
                    task_id=task_id, status=status)

def trace_stream_start(context_id: str, query: str) -> None:
    Tracer.trace_start('stream', 'AGENT_STREAM_START',
                      context_id=context_id, query=query)

def trace_stream_end() -> None:
    Tracer.trace_end('complete', 'AGENT_STREAM_COMPLETE')

def trace_iteration(message_type: str, has_tool_calls: bool = False) -> None:
    details = {'message_type': message_type}
    if has_tool_calls:
        details['has_tool_calls'] = 'true'
    Tracer.trace('iteration', 'LANGGRAPH_ITERATION', **details)

def trace_tool_call(tool_name: str, parameters: dict, call_id: str) -> None:
    Tracer.trace('tool_call', 'TOOL_CALL_DETECTED',
                tool=tool_name, parameters=str(parameters), call_id=call_id)

def trace_tool_execution_start(tool_name: str) -> None:
    Tracer.trace_start('tool_exec', 'TOOL_EXECUTION_START', tool=tool_name)

def trace_tool_execution_end(tool_name: str, result: Any) -> None:
    Tracer.trace_end('complete', 'TOOL_EXECUTION_COMPLETE',
                    tool=tool_name, result=Tracer._format_value(result))

def trace_llm_call(model_id: str, messages_count: int, prompt: str = '') -> None:
    details: dict[str, Any] = {
        'model': model_id,
        'messages_count': messages_count,
    }
    if prompt:
        details['prompt'] = prompt
    Tracer.trace_start('llm_call', 'LLM_CALL_START', **details)

def trace_llm_response(content_length: int, response: str = '') -> None:
    details: dict[str, Any] = {'content_length': content_length}
    if response:
        details['response'] = response
    Tracer.trace_end('llm_response', 'LLM_RESPONSE_RECEIVED', **details)

def trace_response_parsing(tool_calls_found: bool) -> None:
    Tracer.trace('parsing', 'RESPONSE_PARSING',
                tool_calls_found='true' if tool_calls_found else 'false')