import argparse
from bokeh import events
from bokeh.io import output_file, save
from bokeh.layouts import row, column
from bokeh.models import (
    AutocompleteInput,
    BoxAnnotation,
    BoxSelectTool,
    CheckboxGroup,
    ColumnDataSource,
    CustomJS,
    DataTable,
    Dropdown,
    HoverTool,
    HTMLTemplateFormatter,
    MultiSelect,
    Range1d,
    TableColumn,
)

from bokeh.palettes import Category20
from bokeh.plotting import figure
from nonsequitur_lib import *

if __name__ == "__main__":
    timelineplots = list()
    xcoord_to_time_maps = list()
    box_annotations = list()
    trace_event_renderers = list()
    trace_ids = list()
    traces_src = list()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input_folder", type=str, help="Input folder path", required=True
    )
    parser.add_argument(
        "-color",
        "--color",
        type=str,
        help="Path to file which contains mapping between functions and colors",
        required=False,
    )
    parser.add_argument(
        "-title", "--title", type=str, help="Title of the output file", required=False
    )
    arguments = parser.parse_args()

    log_directory = arguments.input_folder
    log_directory_exists = os.path.isdir(log_directory)
    if not log_directory_exists:
        sys.exit("Invalid path for input folder...")

    colorfile = arguments.color

    title = arguments.title
    if title == None:
        print("No title provided, defaulting to using 'NonSequitur' as the title")
        title = "NonSequitur"

    traces = process_trace_files(log_directory)
    execution_start_time, execution_end_time = get_execution_time_range(traces)
    assert (
        execution_end_time >= execution_start_time
    ), "Expected execution end time \
  to be greater than the execution end time"

    if colorfile == None:
        func_to_color = assign_colors_to_functions(traces)
    else:
        colorfile_exists = os.path.isfile(colorfile)
        if colorfile_exists:
            func_to_color = assign_colors_from_file(traces, colorfile)

        else:
            sys.exit("Invalid path for the color mapping file")

    func_to_color = dict(sorted(func_to_color.items()))

    plot_x_range_start = execution_start_time
    pixels_per_timeunit = TIMELINE_PX_WIDTH / (
        execution_end_time - execution_start_time
    )

    for i in range(len(traces)):
        trace_id = i + 1
        trace_ids.append(trace_id)

        trace = traces[i]
        max_callstack_depth = trace.callstack_depth.max()

        plot_title = "Thread " + str(trace_id)
        timelineplot = figure(
            title=plot_title, tools=[], toolbar_location=None, width=TIMELINE_PX_WIDTH
        )

        timelineplot.xgrid.visible = False
        timelineplot.xaxis.visible = False
        timelineplot.ygrid.visible = False
        timelineplot.yaxis.visible = False

        timelineplot.y_range = Range1d(max_callstack_depth + 3, 0)

        plot_height = max(
            (max_callstack_depth + 2) * MIN_CALLSTACK_PX_HEIGHT, MIN_TIMELINE_PX_HEIGHT
        )
        timelineplot.height = plot_height

        select_interval_tool = BoxSelectTool(dimensions="width")
        timelineplot.add_tools(select_interval_tool)
        timelineplot.toolbar.active_drag = select_interval_tool

        timelineplots.append(timelineplot)

        trace_event_CDS, bracket_CDS, xcoord_to_time = fill_CDS_and_time_maps(
            trace, pixels_per_timeunit, func_to_color
        )

        traces_src.append(trace_event_CDS)
        last_trace_event_x_position = trace_event_CDS.data["right"][-1]
        trace_end_time = trace["end_time"][len(trace) - 1]

        if last_trace_event_x_position > execution_end_time:
            scale_factor = float(trace_end_time - execution_start_time) / float(
                execution_end_time - execution_start_time
            )
            scale_factor = max(scale_factor, 0.2)

            plot_x_range_end = execution_start_time + (
                (last_trace_event_x_position - execution_start_time) / scale_factor
            )

        else:
            plot_x_range_end = execution_end_time

        timelineplot.x_range = Range1d(plot_x_range_start, plot_x_range_end)

        if xcoord_to_time[0]["time"] != execution_start_time:
            xcoord_to_time.appendleft(
                {"x": plot_x_range_start, "time": execution_start_time}
            )

        if xcoord_to_time[-1]["time"] != execution_end_time:
            xcoord_to_time.append({"x": plot_x_range_end, "time": execution_end_time})

        xcoord_to_time_maps.append(xcoord_to_time)

        trace_event_renderer = timelineplot.quad(
            top="top",
            bottom="bottom",
            left="left",
            right="right",
            line_alpha="line_alpha",
            fill_color="color",
            fill_alpha="alpha",
            line_color="black",
            line_width=1,
            source=trace_event_CDS,
        )
        trace_event_renderer.selection_glyph = None
        trace_event_renderer.nonselection_glyph = None

        trace_event_renderers.append(trace_event_renderer)

        timelineplot.multi_line(
            xs="xs",
            ys="ys",
            line_width=1,
            line_alpha=1,
            line_color="black",
            source=bracket_CDS,
        )

        box_annotation = BoxAnnotation(
            left=execution_start_time, fill_alpha=0, fill_color="#009933"
        )
        box_annotations.append(box_annotation)

    for i in range(len(traces)):
        timelineplot = timelineplots[i]
        trace_event_renderer = trace_event_renderers[i]

        xcoord_to_time = xcoord_to_time_maps[i]
        if xcoord_to_time[0]["time"] != execution_start_time:
            xcoord_to_time.appendleft(
                {"x": plot_x_range_start, "time": execution_start_time}
            )

        if xcoord_to_time[-1]["time"] != execution_end_time:
            xcoord_to_time.append({"x": plot_x_range_end, "time": execution_end_time})

        xcoord_to_time_maps[i] = list(xcoord_to_time)

        hover_callback = CustomJS(
            args=dict(
                plot_idx=i,
                trace_events=trace_event_renderer.data_source,
                box_annotations=box_annotations,
                xcoord_to_time_maps=xcoord_to_time_maps,
                min_annotation_width=MIN_CALLSTACK_PX_WIDTH / pixels_per_timeunit,
            ),
            code="""
        function to_x_coords(t0, t1, xcoord_to_time){
          let x0 = null;
          let x1 = null;
        
          for (let i = 0; i < xcoord_to_time.length; i++){
            if (x0 == null && t0 <= xcoord_to_time[i]['time']){
              if (i == 0){
                x0 = xcoord_to_time[i]['x'];
              } else {
                x0 = ((t0 - xcoord_to_time[i - 1]['time']) /
                (xcoord_to_time[i]['time'] -
                xcoord_to_time[i - 1]['time']) *
                (xcoord_to_time[i]['x'] -
                xcoord_to_time[i - 1]['x'])) +
                xcoord_to_time[i - 1]['x'];
              }
            }
          
            if (x1 == null && t1 <= xcoord_to_time[i]['time']){
              x1 = ((t1 - xcoord_to_time[i - 1]['time']) /
              (xcoord_to_time[i]['time'] -
              xcoord_to_time[i - 1]['time']) *
              (xcoord_to_time[i]['x'] -
              xcoord_to_time[i - 1]['x'])) +
              xcoord_to_time[i - 1]['x'];
            }
          
            if (x0 != null && x1 != null){
              return [x0, x1];
            }
          }
        }
      
        function to_time_coords(x0, x1, xcoord_to_time){
          let t0 = null;
          let t1 = null;
          for (let i = 0; i < xcoord_to_time.length; i++){
            if (t0 == null && x0 <= xcoord_to_time[i]['x']){
              if (i == 0){
                t0 = xcoord_to_time[i]['time'];
              } else {
                t0 = ((x0 - xcoord_to_time[i - 1]['x']) /
                (xcoord_to_time[i]['x'] -
                xcoord_to_time[i - 1]['x']) *
                (xcoord_to_time[i]['time'] -
                xcoord_to_time[i - 1]['time'])) +
                xcoord_to_time[i - 1]['time']
              }
            }
          
            if (t1 == null && x1 <= xcoord_to_time[i]['x']){
              t1 = ((x1 - xcoord_to_time[i - 1]['x']) /
              (xcoord_to_time[i]['x'] -
              xcoord_to_time[i - 1]['x']) *
              (xcoord_to_time[i]['time'] -
              xcoord_to_time[i - 1]['time'])) +
              xcoord_to_time[i - 1]['time'];
            }
          
            if (t0 != null && t1 != null){
              return [t0, t1];
            }
          }
        }

        const indices = cb_data.index.indices;
        for (let i = 0; i < indices.length; i++){
          let interval_start_time = trace_events.data['start_time'][indices[0]];
          let interval_end_time = trace_events.data['end_time'][indices[0]];
          let x_coords = null;
        
          for (let j = 0; j < box_annotations.length; j++){
            x_coords = to_x_coords(interval_start_time,
            interval_end_time,
            xcoord_to_time_maps[j]);
            
            let min_x_value = xcoord_to_time_maps[j][0]['x'];
            let max_x_value =
            xcoord_to_time_maps[j][xcoord_to_time_maps[j].length - 1]['x'];
            let x_coord_0 = x_coords[0];
            let x_coord_1 = x_coords[1];
            
            if (box_annotations[j]['fill_color'] == "#009933"){
              if (x_coord_1 - x_coord_0 < min_annotation_width){
                if (x_coord_0 + min_annotation_width > max_x_value){
                  x_coord_0-=min_annotation_width;
                  
                } else {
                  x_coord_1 = x_coord_0 + min_annotation_width;
                }
              }
            
              box_annotations[j]['left'] = x_coord_0;
              box_annotations[j]['right'] = x_coord_1;
              box_annotations[j]['fill_alpha'] = 0.1;
              box_annotations[j]['line_alpha'] = 0;
            }
          }
        }
      """,
        )

        hover_tooltip = HoverTool(
            tooltips=[("Function", "@function"), ("Duration", "@duration")],
            renderers=[trace_event_renderer],
            callback=hover_callback,
        )
        timelineplot.add_tools(hover_tooltip)

        timelineplot.add_layout(box_annotations[i])

        tap_callback = CustomJS(
            args=dict(box_annotations=box_annotations),
            code="""
              for (let i = 0; i < box_annotations.length; i++){
                if (box_annotations[i]['fill_color'] == "#009933") {
                  box_annotations[i]['fill_color'] = "#E0AC28";  
                  box_annotations[i]['fill_alpha'] = 0.3;            
                }
              }
        """,
        )

        timelineplot.js_on_event(events.Tap, tap_callback)

        doubletap_callback = CustomJS(
            args=dict(box_annotations=box_annotations),
            code="""
              for (let i = 0; i < box_annotations.length; i++){
                box_annotations[i]['fill_color'] = "#009933";
                box_annotations[i]['fill_alpha'] = 0;
              }
        """,
        )

        timelineplot.js_on_event(events.DoubleTap, doubletap_callback)

    timelineplots_layout = column(timelineplots, sizing_mode="scale_width")

    func_names = list(func_to_color.keys())
    color_values = list()
    opacity_values = list()
    for color_and_opacity in list(func_to_color.values()):
        color = color_and_opacity[0]
        opacity = color_and_opacity[1]
        color_values.append(color)
        opacity_values.append(opacity)

    trace_select_values = list()
    thread_select_options = list()
    for i in range(len(traces)):
        trace_id = i + 1
        trace_select_values.append(str(i))
        thread_select_options.append((str(i), str(trace_id)))

    thread_select = MultiSelect(
        value=trace_select_values,
        title="Thread ID",
        height=150,
        options=thread_select_options,
    )

    legend_data = {"func": func_names, "color": color_values, "opacity": opacity_values}
    legend_src = ColumnDataSource(legend_data)
    template = """                
            <div style="background:<%= color %>; opacity:<%= opacity %>;">
                &ensp;
            </div>
    """
    formatter = HTMLTemplateFormatter(template=template)
    columns = [
        TableColumn(field="func", title="Function"),
        TableColumn(field="color", title="Color", formatter=formatter),
    ]
    legend = DataTable(
        source=legend_src, columns=columns, height=150, sizing_mode="stretch_width"
    )

    highlight_funcs = CustomJS(
        args=dict(
            legend_src=legend_src,
            func_to_color=func_to_color,
            thread_select=thread_select,
            traces_src=traces_src,
        ),
        code="""
           const funcs_to_highlight = [];
           const threads_being_displayed = thread_select.value;
           
           for (const i of cb_obj.indices) {
             const func_to_highlight = legend_src.data['func'][i].toString();
             funcs_to_highlight.push(func_to_highlight);
           }
          
           if (funcs_to_highlight.length > 0){
             for (let i = 0; i < threads_being_displayed.length; i++){
               let thread = threads_being_displayed[i];
               const funcs_in_thread = traces_src[thread].data['function'];
               for (let j = 0; j < funcs_in_thread.length; j++){
                 let func = funcs_in_thread[j];
                 if (funcs_to_highlight.indexOf(func) != -1){
                   let alpha = func_to_color[func][1];
                   traces_src[thread].data['alpha'][j] = alpha;
                   traces_src[thread].data['line_alpha'][j] = 1;   
              
                 } else {
                   traces_src[thread].data['alpha'][j] = 0.2;
                   traces_src[thread].data['line_alpha'][j] = 0;
                 }
               }
             
               traces_src[thread].change.emit();
             }
           } else {
               for (let i = 0; i < traces_src.length; i++){
                 const funcs_in_thread = traces_src[i].data['function'];
                 for (let j = 0; j < funcs_in_thread.length; j++){
                   let func = funcs_in_thread[j];
                   let alpha = func_to_color[func][1];
                   traces_src[i].data['alpha'][j] = alpha;
                   traces_src[i].data['line_alpha'][j] = 0;
                 }
                 traces_src[i].change.emit();
               }
           }
    """,
    )
    legend_src.selected.js_on_change("indices", highlight_funcs)

    func_names = list(func_to_color.keys())
    function_search = AutocompleteInput(
        title="Enter a function name:",
        completions=func_names,
        sizing_mode="stretch_width",
    )

    thread_select.js_on_change(
        "value",
        CustomJS(
            args=dict(
                plots=timelineplots,
                layout=timelineplots_layout,
                function_search=function_search,
                traces_src=traces_src,
                func_to_color=func_to_color,
                legend_src=legend_src,
            ),
            code="""
           const children = [];
           const function_names = [];
           const color_values = [];
           const opacity_values = [];
           const highlighted_funcs = [];
           const indices_of_highlighted_funcs = [];
           
           for (const i of legend_src.selected.indices) {
             const highlighted_func = legend_src.data['func'][i];
             highlighted_funcs.push(highlighted_func);
           }
           
           legend_src.selected.indices = [];
           
           for (const i of this.value) {
             children.push(plots[i]);
           }
           
           layout.children = children;
         
           for (let i = 0; i < this.value.length; i++){
             const selected_thread = this.value[i];
             const functions_in_thread = traces_src[selected_thread].data['function'];
             
             for (let j = 0; j < functions_in_thread.length; j++){
               let func = functions_in_thread[j];
               if (function_names.includes(func) == false){
                 function_names.push(func);
               }
             }
           }
           
           function_names.sort();
           for (let i = 0; i < function_names.length; i++){
             let func = function_names[i];
             let color = func_to_color[func][0];
             let opacity = func_to_color[func][1];
             color_values.push(color);
             opacity_values.push(opacity);
           }
           
           for (const highlighted_func of highlighted_funcs){
             const index = function_names.indexOf(highlighted_func);
             if (index != -1){
               indices_of_highlighted_funcs.push(index);
             }
           }
           
           debugger;
           
           legend_src.data['func'] = function_names;
           legend_src.data['color'] = color_values;
           legend_src.data['opacity'] = opacity_values;
           legend_src.change.emit();
           legend_src.selected.indices = indices_of_highlighted_funcs;
           
           function_search.value = '';

    """,
        ),
    )

    function_search.js_on_change(
        "value",
        CustomJS(
            args=dict(
                func_to_color=func_to_color,
                thread_select=thread_select,
                traces_src=traces_src,
                legend_src=legend_src,
            ),
            code="""
      let selected_func = this.value;

      const threads_to_display = [];
      
      if (selected_func != ''){
        for (let i = 0; i < traces_src.length; i++){
          const trace = traces_src[i];
          for (let j = 0; j < trace.data['function'].length; j++){

            const thread_id = i.toString();
            if (trace.data['function'][j] == selected_func && \
            threads_to_display.includes(thread_id) == false){
              threads_to_display.push(thread_id);
            }              
            
          }
          
        }
        thread_select.value = threads_to_display;
        this.value = selected_func;
      }
 
    """,
        ),
    )

    output_file(title + ".html")

    widget_layout = row(
        thread_select,
        column(function_search, legend, sizing_mode="stretch_width"),
        sizing_mode="scale_width",
    )
    save(
        column(widget_layout, timelineplots_layout, sizing_mode="scale_width"),
        title=title,
    )
