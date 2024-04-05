# NonSequitur

## Introduction
NonSequitur is a trace visualization tool designed to assist developers in analyzing performance issues in multi-threaded applications. It leverages the RegTime algorithm, which compresses execution traces to manageable sizes without sacrificing critical information necessary for effective performance debugging. This tool is particularly useful in environments where understanding latency spikes and throughput drops in applications is crucial.

## Features
- **Trace Compression**: Utilizes the RegTime algorithm to compress multi-threaded execution traces while retaining key performance debugging information.
- **Visualization**: Provides a compact visual representation of compressed execution traces, making large traces navigable without horizontal scrolling.
- **Performance Analysis**: Enhances the ability to spot outlier events and performance bottlenecks in threaded applications.

## Demo Instructions
We have provided a small execution trace in the `example_trace` folder so you can visualize it with NonSequitur. Follow the instructions below to generate the visualization:

```bash
pip install -r requirements.txt
python nonsequitur.py -i example_trace
```

If, for some reason, you are unable to run the code, we have also provided an example of a NonSequitur visualization: NonSequitur_Vis_Example.html.