import argparse
from config import ENTER, EXIT, ENTER_EVENTTYPE, EXECUTE_EVENTTYPE, EXIT_EVENTTYPE
import copy
import os
from os.path import dirname, join
import pandas as pd
import pickle
import re
from traceProcessing import process_line_from_trace, get_file_size
from tqdm import tqdm

THRESHOLD = 1


def get_small_functions(tracefile_path):
    firstStartTime = None
    finalEndTime = None
    totalDurationForFunction = dict()
    start_timeAtCallStackDepth = list()
    callstack_depth = 0
    smallFunctions = list()

    fileSize = get_file_size(tracefile_path)

    with open(tracefile_path, "r") as f:
        for line in tqdm(f):
            traceEvent = process_line_from_trace(line)
            if firstStartTime == None:
                firstStartTime = traceEvent["time"]

            if traceEvent["direction"] == ENTER:
                start_time = traceEvent["time"]
                if callstack_depth == len(start_timeAtCallStackDepth):
                    start_timeAtCallStackDepth.append(start_time)
                else:
                    assert callstack_depth < len(start_timeAtCallStackDepth)
                    start_timeAtCallStackDepth[callstack_depth] = start_time

                callstack_depth += 1

            else:
                callstack_depth -= 1
                function = traceEvent["function"]
                end_time = traceEvent["time"]
                start_time = start_timeAtCallStackDepth[callstack_depth]
                duration = end_time - start_time
                totalDurationForFunction[function] = (
                    totalDurationForFunction.get(function, 0) + duration
                )
                assert callstack_depth == len(start_timeAtCallStackDepth) - 1
                del start_timeAtCallStackDepth[-1]

        finalEndTime = traceEvent["time"]

        for function in totalDurationForFunction:
            totalDuration = totalDurationForFunction[function]
            if (totalDuration / (finalEndTime - firstStartTime)) <= THRESHOLD / 100:
                smallFunctions.append(function)

        return smallFunctions


def output_sanity_check(filtered_trace, totalFuncDurationBefore):
    function_at_callstack = list()
    total_duration_for_func = dict()

    for event in filtered_trace:
        function = event["function"]
        callstack_depth = event["callstack_depth"]
        duration = event["duration"]
        event_type = event["event_type"]

        if event_type != EXIT_EVENTTYPE:
            total_duration_for_func[function] = (
                total_duration_for_func.get(function, 0) + duration
            )

        if event_type == ENTER_EVENTTYPE:
            assert len(function_at_callstack) == callstack_depth
            function_at_callstack.append(function)

        elif event_type == EXIT_EVENTTYPE:
            assert function_at_callstack[-1] == function
            function_at_callstack.pop()

    assert len(total_duration_for_func) == len(totalFuncDurationBefore)
    for function in total_duration_for_func:
        assert total_duration_for_func[function] == totalFuncDurationBefore[function]


def filter_trace_file(tracefile_path):
    lastFuncEntered = {"name": None, "time": None}
    nonLeafFuncEntered = list()
    lastEnterTime = None
    callstack_depth = 0
    filtered_trace = list()
    totalFuncDurationBefore = dict()

    functions_to_remove = get_small_functions(tracefile_path)
    fileSize = get_file_size(tracefile_path)

    with open(tracefile_path, "r") as f:
        for line in tqdm(f):
            filtered_trace_event = None
            trace_event = process_line_from_trace(line)

            if trace_event["function"] in functions_to_remove:
                continue

            if trace_event["direction"] == ENTER:
                if lastFuncEntered["name"] != None:
                    filtered_trace_event = {
                        "event_type": ENTER_EVENTTYPE,
                        "function": lastFuncEntered["name"],
                        "start_time": lastFuncEntered["time"],
                        "end_time": lastFuncEntered["time"],
                        "time_first_entered": -1,
                        "time_last_exited": -1,
                        "duration": 0,
                        "parens": 0,
                        "callstack_depth": callstack_depth,
                    }

                    filtered_trace.append(filtered_trace_event)

                    nonLeafFuncEntered.append(dict())
                    nonLeafFuncEntered[-1]["name"] = lastFuncEntered["name"]
                    nonLeafFuncEntered[-1]["time"] = lastFuncEntered["time"]
                    nonLeafFuncEntered[-1]["index"] = len(filtered_trace) - 1

                    callstack_depth += 1

                lastFuncEntered["name"] = trace_event["function"]
                lastFuncEntered["time"] = trace_event["time"]

            elif trace_event["function"] == lastFuncEntered["name"]:
                duration = trace_event["time"] - lastFuncEntered["time"]
                totalFuncDurationBefore[trace_event["function"]] = (
                    totalFuncDurationBefore.get(trace_event["function"], 0) + duration
                )

                filtered_trace_event = {
                    "event_type": EXECUTE_EVENTTYPE,
                    "function": trace_event["function"],
                    "start_time": lastFuncEntered["time"],
                    "end_time": trace_event["time"],
                    "time_first_entered": -1,
                    "time_last_exited": -1,
                    "duration": duration,
                    "parens": 0,
                    "callstack_depth": callstack_depth,
                }

                filtered_trace.append(filtered_trace_event)

                lastFuncEntered = {"name": None, "time": None}

            else:
                lastNonLeafFuncEntered = nonLeafFuncEntered.pop()
                assert trace_event["function"] == lastNonLeafFuncEntered["name"]

                duration = trace_event["time"] - lastNonLeafFuncEntered["time"]

                totalFuncDurationBefore[trace_event["function"]] = (
                    totalFuncDurationBefore.get(trace_event["function"], 0) + duration
                )

                indexOfEnterEvent = lastNonLeafFuncEntered["index"]
                filtered_trace[indexOfEnterEvent]["duration"] = duration

                callstack_depth -= 1

                filtered_trace_event = {
                    "event_type": EXIT_EVENTTYPE,
                    "function": trace_event["function"],
                    "start_time": trace_event["time"],
                    "end_time": trace_event["time"],
                    "time_first_entered": -1,
                    "time_last_exited": -1,
                    "duration": duration,
                    "parens": 0,
                    "callstack_depth": callstack_depth,
                }

                filtered_trace.append(filtered_trace_event)

    output_sanity_check(filtered_trace, totalFuncDurationBefore)

    return filtered_trace
