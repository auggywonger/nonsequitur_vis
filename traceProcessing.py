import os
import re


def process_line_from_trace(line):
    traceEventTuple = {}

    listFromLine = line.split(" ")
    traceEventTuple["direction"] = listFromLine[0]
    traceEventTuple["function"] = listFromLine[1]
    traceEventTuple["time"] = int(listFromLine[2])
    return traceEventTuple


def get_file_size(filepath):
    return os.path.getsize(filepath)
