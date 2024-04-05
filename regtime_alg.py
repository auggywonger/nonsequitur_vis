from collections import namedtuple
from config import (
    ENTER,
    EXIT,
    ENTER_EVENTTYPE,
    EXECUTE_EVENTTYPE,
    EXIT_EVENTTYPE,
    AGGREGATION_LEFTBOUND,
    AGGREGATION_RIGHTBOUND,
)
from tqdm import tqdm

CallDurationThresh = 0.01
CallGapThresh = 0.001
TotalTimeFractionThresh = 0.13

class CallStackTreeNode:
    def __init__(self, function=None, callstack_depth=None, total_duration=0):
        self.function = function
        self.callstack_depth = callstack_depth
        self.total_duration = total_duration
        self.childnode_to_index = dict()
        self.childnode_to_duration = dict()

    def has_child_node(self, trace_event):
        has_child_node = False

        function = trace_event["function"]
        child_node_index = self.childnode_to_index.get(function, -1)
        if child_node_index > -1:
            has_child_node = True

        return has_child_node

    def get_index_to_child_node(self, trace_event):
        function = trace_event["function"]
        return self.childnode_to_index[function]

    def add_child_node(self, trace_event, index):
        function = trace_event["function"]
        self.childnode_to_index[function] = index


class RegTimeVisualEncoding:
    def __init__(self):
        self.index_to_node_at_level = [0]
        self.callstack_tree = [CallStackTreeNode()]
        self.callstack_depth = None
        self.start_time = None
        self.end_time = None

    def add_event(self, event):
        if self.start_time == None:
            self.start_time = event["start_time"]
            self.callstack_depth = event["callstack_depth"]

        index_to_current_node = self.index_to_node_at_level[-1]
        current_callstack_tree_node = self.callstack_tree[index_to_current_node]

        if event["event_type"] != EXIT_EVENTTYPE:
            if current_callstack_tree_node.has_child_node(event):
                index_to_child_node = (
                    current_callstack_tree_node.get_index_to_child_node(event)
                )
                self.callstack_tree[index_to_child_node].total_duration += event[
                    "duration"
                ]

            else:
                callstack_tree_node = CallStackTreeNode(
                    event["function"], event["callstack_depth"], event["duration"]
                )

                current_callstack_tree_node.add_child_node(
                    event, len(self.callstack_tree)
                )
                self.callstack_tree.append(callstack_tree_node)

            index_to_child_node = current_callstack_tree_node.get_index_to_child_node(
                event
            )
            if event["event_type"] == ENTER_EVENTTYPE:
                self.index_to_node_at_level.append(index_to_child_node)

        else:
            self.index_to_node_at_level.pop()

        self.end_time = event["end_time"]

    def write_out(self, trace):
        assert self.index_to_node_at_level == [
            0
        ], "Writing out regtime visual encoding when encoding is not complete"

        regtime_vis_encoding_start = len(trace)

        node_indices_at_level = [[0]]
        previous_level = None
        current_level = 0
        while current_level >= 0:
            assert (
                current_level == len(node_indices_at_level) - 1
            ), "Unexpected value for current_level"

            if previous_level != None and previous_level >= current_level:
                node_indices_at_level[current_level].pop()

            if len(node_indices_at_level[current_level]) > 0:
                index_to_current_node = node_indices_at_level[-1][-1]
                current_callstack_tree_node = self.callstack_tree[index_to_current_node]

                is_root_node = current_callstack_tree_node.function == None
                if not is_root_node:
                    previous_level = current_level

                num_of_childnodes = len(current_callstack_tree_node.childnode_to_index)
                has_child_nodes = num_of_childnodes > 0
                if has_child_nodes:
                    if not is_root_node:
                        event = {
                            "event_type": ENTER_EVENTTYPE,
                            "function": current_callstack_tree_node.function,
                            "start_time": self.start_time,
                            "end_time": self.end_time,
                            "callstack_depth": current_callstack_tree_node.callstack_depth,
                            "duration": current_callstack_tree_node.total_duration,
                            "parens": 0,
                        }

                        trace.append(event)

                    node_indices_at_level.append(list())

                    sorted_callstack_tree_child_nodes = sorted(
                        current_callstack_tree_node.childnode_to_index.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                    for (
                        child_function,
                        index_to_child_node,
                    ) in sorted_callstack_tree_child_nodes:
                        node_indices_at_level[current_level + 1].append(
                            index_to_child_node
                        )

                    current_level += 1

                else:
                    event = {
                        "event_type": EXECUTE_EVENTTYPE,
                        "function": current_callstack_tree_node.function,
                        "start_time": self.start_time,
                        "end_time": self.end_time,
                        "callstack_depth": current_callstack_tree_node.callstack_depth,
                        "duration": current_callstack_tree_node.total_duration,
                        "parens": 0,
                    }

                    trace.append(event)

            else:
                node_indices_at_level.pop()
                previous_level = current_level
                current_level -= 1

                if current_level > 0:
                    index_to_current_node = node_indices_at_level[-1][-1]
                    current_callstack_tree_node = self.callstack_tree[
                        index_to_current_node
                    ]

                    is_root_node = current_callstack_tree_node.function == None

                    if not is_root_node:
                        event = {
                            "event_type": EXIT_EVENTTYPE,
                            "function": current_callstack_tree_node.function,
                            "start_time": self.start_time,
                            "end_time": self.end_time,
                            "callstack_depth": current_callstack_tree_node.callstack_depth,
                            "duration": current_callstack_tree_node.total_duration,
                            "parens": 0,
                        }

                        trace.append(event)

        num_events_in_regtime_vis_encoding = len(trace) - regtime_vis_encoding_start
        if num_events_in_regtime_vis_encoding > 1:
            trace[regtime_vis_encoding_start]["parens"] = AGGREGATION_LEFTBOUND
            trace[-1]["parens"] = AGGREGATION_RIGHTBOUND


def output_sanity_check(input_trace, output_trace):
    input_trace_func_to_duration = dict()
    output_trace_func_to_duration = dict()
    regtime_vis_encoding = None

    for event in input_trace:
        function = event["function"]
        duration = event["duration"]
        event_type = event["event_type"]

        if event_type != EXIT_EVENTTYPE:
            input_trace_func_to_duration[function] = (
                input_trace_func_to_duration.get(function, 0) + duration
            )

    for event in output_trace:
        function = event["function"]
        duration = event["duration"]
        event_type = event["event_type"]

        if event_type != EXIT_EVENTTYPE:
            output_trace_func_to_duration[function] = (
                output_trace_func_to_duration.get(function, 0) + duration
            )

    assert (
        input_trace_func_to_duration == output_trace_func_to_duration
    ), "Trace event durations not matching"

    grp_vis_encode_start = None
    grp_vis_encode_length = 0
    regtime_vis_encoding = None
    last_grp_vis_encode = None

    for index in range(len(output_trace)):
        event = output_trace[index]
        discovered_grp_vis_encode = event["parens"] == AGGREGATION_LEFTBOUND
        grp_vis_encode_ended = event["parens"] == AGGREGATION_RIGHTBOUND
        grp_vis_encode_exists = regtime_vis_encoding != None

        if grp_vis_encode_exists:
            grp_vis_encode_length += 1

        elif discovered_grp_vis_encode:
            assert (
                not grp_vis_encode_exists
            ), "Encountered another regtime visual encoding before previous one ended"

            regtime_vis_encoding = RegTimeVisualEncoding()
            regtime_vis_encoding.start_time = event["start_time"]
            grp_vis_encode_start = index
            grp_vis_encode_length += 1

        elif grp_vis_encode_ended:
            assert (
                grp_vis_encode_exists
            ), "Encountered end of a regtime visual encoding before beginning"

            regtime_vis_encoding.end_time = event["end_time"]

            assert (
                regtime_vis_encoding.end_time > regtime_vis_encoding.start_time
            ), "regtime visual encoding start time greater than its end time"

            subtrace = output_trace[
                grp_vis_encode_start : grp_vis_encode_start + grp_vis_encode_length
            ]
            for subtrace_event in subtrace:
                assert (
                    subtrace_event["start_time"] == regtime_vis_encoding.start_time
                ), "Unexpected start time in regtime visual encoding"

                assert (
                    subtrace_event["end_time"] == regtime_vis_encoding.end_time
                ), "Unexpected start time in regtime visual encoding"

            if last_grp_vis_encode != None:
                assert (
                    last_grp_vis_encode.end_time < regtime_vis_encoding.start_time
                ), "regtime visual encodings overlapping"

            last_grp_vis_encode = RegTimeVisualEncoding()
            last_grp_vis_encode.start_time = regtime_vis_encoding.start_time
            last_grp_vis_encode.end_time = regtime_vis_encoding.end_time

            grp_vis_encode_length = 0
            regtime_vis_encoding = None


def regtime(input_trace):
    output_trace = list()
    regtime_vis_encoding = None
    thread_duration = input_trace[-1]["end_time"] - input_trace[0]["start_time"]

    for trace_event in tqdm(input_trace):
        started_regtime_expr = regtime_vis_encoding != None
        if started_regtime_expr:
            callstack_depth_out_of_range = (
                trace_event["callstack_depth"] < regtime_vis_encoding.callstack_depth
            )

            event_with_long_duration = (
                trace_event["event_type"] != EXIT_EVENTTYPE
                and trace_event["duration"] >= CallDurationThresh * thread_duration
            )

            reached_max_time_interval = (
                regtime_vis_encoding.end_time - regtime_vis_encoding.start_time
                >= TotalTimeFractionThresh * thread_duration
            )

            encountered_idle_time = (
                trace_event["start_time"] - regtime_vis_encoding.end_time
                >= CallGapThresh * thread_duration
            )

            stop_regtime_expr = (
                trace_event["callstack_depth"] == regtime_vis_encoding.callstack_depth
                and trace_event["event_type"] != EXIT_EVENTTYPE
                and (
                    event_with_long_duration
                    or reached_max_time_interval
                    or encountered_idle_time
                )
            ) or callstack_depth_out_of_range

            if stop_regtime_expr:
                regtime_vis_encoding.write_out(output_trace)
                regtime_vis_encoding = None

            else:
                regtime_vis_encoding.add_event(trace_event)

        started_regtime_expr = regtime_vis_encoding != None
        if (
            not started_regtime_expr
            and trace_event["event_type"] != EXIT_EVENTTYPE
            and trace_event["duration"] < 0.01 * thread_duration
        ):
            regtime_vis_encoding = RegTimeVisualEncoding()
            regtime_vis_encoding.add_event(trace_event)

        elif not started_regtime_expr:
            output_trace.append(trace_event)

    started_regtime_expr = regtime_vis_encoding != None
    if started_regtime_expr:
        regtime_vis_encoding.write_out(output_trace)

    output_sanity_check(input_trace, output_trace)
    #    print("Compressed Length:" + str(len(output_trace)))
    return output_trace
