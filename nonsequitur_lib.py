from bokeh.models import ColumnDataSource
from bokeh.palettes import Category20
from collections import deque
from regtime_alg import *
import math
import numpy as np
from operator import itemgetter
import os
from os.path import dirname, join
import pandas as pd
import subprocess
import sys
from traceFilter import filter_trace_file
from tqdm import tqdm

TIMELINE_PX_WIDTH = 1300
MIN_CALLSTACK_PX_WIDTH = 4
MIN_CALLSTACK_PX_HEIGHT = 10
MIN_TIMELINE_PX_HEIGHT = 70
PIXELS_BTW_EVENTS = 2
SPACE_BTW_CALLSTACK_DEPTHS = 0.15
DEFAULT_FUNC_COLOR = "#bab0ac"


def get_tracefilenames_in_directory(dir):
    tracefile_names = os.listdir(dir)
    return sorted(tracefile_names)


def process_trace_files(dir):
    traces = list()

    tracefile_names = get_tracefilenames_in_directory(dir)

    for tracefile_name in tqdm(tracefile_names):
        tracefile_path = dir + "/" + tracefile_name
        trace = filter_trace_file(tracefile_path)

        add_regtime_exprs = len(trace) > TIMELINE_PX_WIDTH / MIN_CALLSTACK_PX_WIDTH
        if add_regtime_exprs:
            trace = regtime(trace)

        traces.append(pd.DataFrame(trace))

    return traces


def get_execution_time_range(traces):
    execution_start_time = None
    execution_end_time = None

    for trace in traces:
        if execution_start_time == None:
            execution_start_time = trace["start_time"][0]
        else:
            execution_start_time = min(execution_start_time, trace["start_time"][0])

        if execution_end_time == None:
            execution_end_time = trace["end_time"][len(trace) - 1]

        else:
            execution_end_time = max(
                execution_end_time, trace["end_time"][len(trace) - 1]
            )

    return execution_start_time, execution_end_time


def assign_colors_from_file(traces, colorfile):
    func_to_color_from_file = dict()
    func_to_color = dict()

    with open(colorfile, "r") as f:
        for line in f:
            listfromline = line.split(" ")

            function = listfromline[0]
            color = listfromline[1]
            alpha = float(listfromline[2])

            func_to_color_from_file[function] = (color, alpha)

    for trace in traces:
        unique_func_names_in_trace = trace.function.unique().tolist()

        for func_name in unique_func_names_in_trace:
            func_to_color[func_name] = func_to_color_from_file.get(
                func_name, (DEFAULT_FUNC_COLOR, 1)
            )

    return func_to_color


def define_color_palette():
    color_palette = list()
    for color in Category20[20]:
        color_palette.append((color, 1))

    for color in Category20[20]:
        color_palette.append((color, 0.7))

    return color_palette


def assign_colors_to_functions(traces):
    func_to_color = dict()
    func_to_num_of_occurrences = dict()
    func_to_num_of_threads = dict()
    func_to_ranking = dict()

    for trace in traces:
        unique_func_names_in_trace = trace.function.unique().tolist()

        for func_name in unique_func_names_in_trace:
            event_is_func = trace.function == func_name
            event_type_not_exit = trace.event_type != EXIT_EVENTTYPE

            num_of_occurrences = trace[
                event_is_func & event_type_not_exit
            ].function.count()
            func_to_num_of_occurrences[func_name] = (
                func_to_num_of_occurrences.get(func_name, 0) + num_of_occurrences
            )
            func_to_num_of_threads[func_name] = (
                func_to_num_of_threads.get(func_name, 0) + 1
            )

    for func_name in func_to_num_of_occurrences.keys():
        num_of_occurrences = func_to_num_of_occurrences[func_name]
        num_of_threads = func_to_num_of_threads[func_name]
        func_to_ranking[func_name] = num_of_occurrences * num_of_threads

    sorted_func_rankings = sorted(
        func_to_ranking.items(), key=itemgetter(1), reverse=True
    )

    color_palette = define_color_palette()
    i = 0
    for func, ranking in sorted_func_rankings:
        if len(func_to_color) >= len(color_palette):
            func_to_color[func] = (DEFAULT_FUNC_COLOR, 1)

        else:
            func_to_color[func] = color_palette[i]

        i += 1

    return func_to_color


def fill_CDS_and_time_maps(trace, pixels_per_timeunit, func_to_color):
    top_attributes = list()
    bottom_attributes = list()
    left_attributes = list()
    right_attributes = list()
    color_attributes = list()
    function_names = list()
    duration_attributes = list()
    alpha_attributes = list()
    line_alpha_attributes = list()
    start_times = list()
    end_times = list()
    ###

    bracket_x_attributes = list()
    bracket_y_attributes = list()

    max_callstack_depth = trace.callstack_depth.max()
    min_leftattr_at_callstack_depth = (max_callstack_depth + 1) * [
        trace["start_time"][0]
    ]
    start_time_at_callstack_depth = (max_callstack_depth + 1) * [trace["start_time"][0]]

    xcoord_to_time = deque()

    found_regtime_expr_start = False

    for index, trace_event in trace.iterrows():
        callstack_depth = trace_event.callstack_depth
        add_rect_attributes = trace_event.event_type != ENTER_EVENTTYPE

        left_attr = None
        right_attr = None

        if add_rect_attributes and (
            found_regtime_expr_start or trace_event["event_type"] == EXIT_EVENTTYPE
        ):
            left_attr = min_leftattr_at_callstack_depth[callstack_depth]

        elif add_rect_attributes:
            min_left_attr = min_leftattr_at_callstack_depth[callstack_depth]
            left_attr = max(trace_event["start_time"], min_left_attr)

        if trace_event["event_type"] == ENTER_EVENTTYPE:
            min_leftattr = min_leftattr_at_callstack_depth[callstack_depth]
            min_leftattr_at_callstack_depth[callstack_depth] = max(
                min_leftattr, trace_event["start_time"]
            )

            left_attr = min_leftattr_at_callstack_depth[callstack_depth]

            min_leftattr_at_callstack_depth[
                callstack_depth + 1
            ] = min_leftattr_at_callstack_depth[callstack_depth]

            start_time_at_callstack_depth[callstack_depth] = trace_event["start_time"]

        if add_rect_attributes:
            trace_event_px_width = max(
                MIN_CALLSTACK_PX_WIDTH / pixels_per_timeunit, trace_event["duration"]
            )
            right_attr = left_attr + trace_event_px_width

            if trace_event["event_type"] == EXIT_EVENTTYPE:
                right_attr = max(
                    right_attr, min_leftattr_at_callstack_depth[callstack_depth + 1]
                )

            top_attr = max_callstack_depth + 2 - callstack_depth

            if callstack_depth == 0:
                bottom_attr = max_callstack_depth + 3 - callstack_depth

            else:
                bottom_attr = (
                    max_callstack_depth
                    + 3
                    - callstack_depth
                    - SPACE_BTW_CALLSTACK_DEPTHS
                )

            function_name = trace_event["function"]

            color_attr, alpha_attr = func_to_color.get(
                function_name, (DEFAULT_FUNC_COLOR, 1)
            )

            duration_in_range_of_secs = trace_event["duration"] / 1000000000 >= 1
            duration_in_range_of_ms = trace_event["duration"] / 1000000 >= 1

            if duration_in_range_of_secs:
                duration_attr = (
                    str(round(trace_event["duration"] / 1000000000, 2)) + " seconds"
                )

            elif duration_in_range_of_ms:
                duration_attr = (
                    str(round(trace_event["duration"] / 1000000, 2)) + " milliseconds"
                )

            else:
                duration_attr = str(trace_event["duration"]) + " nanoseconds"

            if trace_event["event_type"] == EXIT_EVENTTYPE:
                start_time = start_time_at_callstack_depth[callstack_depth]

            else:
                start_time = trace_event["start_time"]

            end_time = trace_event["end_time"]

            top_attributes.append(top_attr)
            bottom_attributes.append(bottom_attr)
            left_attributes.append(left_attr)
            right_attributes.append(right_attr)
            color_attributes.append(color_attr)
            function_names.append(function_name)
            duration_attributes.append(duration_attr)
            alpha_attributes.append(alpha_attr)
            start_times.append(start_time)
            line_alpha_attributes.append(0)
            end_times.append(end_time)

            min_leftattr_at_callstack_depth[callstack_depth] = right_attr + (
                PIXELS_BTW_EVENTS / pixels_per_timeunit
            )

        if not found_regtime_expr_start:
            found_regtime_expr_start = trace_event["parens"] == AGGREGATION_LEFTBOUND

        found_regtime_expr_end = trace_event["parens"] == AGGREGATION_RIGHTBOUND

        repeating_one_event = (
            not found_regtime_expr_start
            and not found_regtime_expr_end
            and trace_event["event_type"] == EXECUTE_EVENTTYPE
            and trace_event["end_time"] - trace_event["start_time"]
            > trace_event["duration"]
        )

        if found_regtime_expr_end:
            found_regtime_expr_start = False
            found_regtime_expr_end = False

        if trace_event["parens"] == AGGREGATION_LEFTBOUND or repeating_one_event:
            assert left_attr != None
            xcoord_to_time.append({"x": left_attr, "time": trace_event["start_time"]})
            regtime_expr_x_start = left_attr

            bracket_x_attributes.append([left_attr, left_attr])

            bracket_y_attr = max_callstack_depth + 3 - callstack_depth
            bracket_y_attributes.append([0, bracket_y_attr])

        if trace_event["parens"] == AGGREGATION_RIGHTBOUND or repeating_one_event:
            assert right_attr != None

            regtime_expr_x_end = max(right_attr, trace_event["end_time"])
            xcoord_to_time.append(
                {"x": regtime_expr_x_end, "time": trace_event["end_time"]}
            )

            bracket_x_attributes.append([regtime_expr_x_start, regtime_expr_x_end])
            bracket_y_attributes.append([0, 0])

            bracket_x_attributes.append([regtime_expr_x_end, regtime_expr_x_end])
            bracket_y_attributes.append([0, bottom_attr])

        if (
            trace_event["parens"] == 0
            and not found_regtime_expr_start
            and not repeating_one_event
        ):
            if trace_event["event_type"] == ENTER_EVENTTYPE:
                left_attr != None
                right_attr == None
                xcoord_to_time.append(
                    {"x": left_attr, "time": trace_event["start_time"]}
                )

            elif trace_event["event_type"] == EXECUTE_EVENTTYPE:
                assert left_attr != None
                assert right_attr != None

                xcoord_to_time.append(
                    {"x": left_attr, "time": trace_event["start_time"]}
                )

                xcoord_to_time.append(
                    {"x": right_attr, "time": trace_event["end_time"]}
                )

            else:
                assert left_attr != None
                assert right_attr != None

                xcoord_to_time.append(
                    {"x": right_attr, "time": trace_event["end_time"]}
                )

    trace_event_CDS = ColumnDataSource(
        data=dict(
            top=top_attributes,
            bottom=bottom_attributes,
            left=left_attributes,
            right=right_attributes,
            color=color_attributes,
            function=function_names,
            duration=duration_attributes,
            alpha=alpha_attributes,
            line_alpha=line_alpha_attributes,
            start_time=start_times,
            end_time=end_times,
        )
    )

    bracket_CDS = ColumnDataSource(
        data=dict(xs=bracket_x_attributes, ys=bracket_y_attributes)
    )

    return trace_event_CDS, bracket_CDS, xcoord_to_time
