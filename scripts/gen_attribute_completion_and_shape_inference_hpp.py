import os


def make_completion_code(op_name,
                         attribute_list=[],
                         shape_inference_code='''
assert(node.input_name_list.size() > 0);
assert(node.output_name_list.size() > 0);
add_variable_to_table(output(0), dtype_of(input(0)), dims_of(input(0)));
''',
                         preprocess="",
                         postprocess=""):
    # attribute completion and definition
    attribute_completion_code_list = []
    attribute_definition_list = []
    for attribute in attribute_list:
        attr_name, attr_type, default_value = attribute
        inner_code = ''
        if default_value is None:
            inner_code = '''
assert(!"attribute not found: {attr_name}");
'''.format(attr_name=attr_name)
        else:
            inner_code = '''
node.attribute_table.emplace(
    "{attr_name}", {default_value});
'''.format(attr_name=attr_name, default_value=default_value)

        attribute_completion_code = '''
{{
    auto found = node.attribute_table.find("{attr_name}");
    if(found == node.attribute_table.end()) {{
        {code}
    }}
}}
'''.format(attr_name=attr_name, attr_type=attr_type, code=inner_code)
        attribute_completion_code_list.append(attribute_completion_code)

        attribute_definition = '''
auto {attr_name} = get<{attr_type}>(node.attribute_table.at("{attr_name}"));
static_cast<void>({attr_name}); // maybe unused
'''.format(attr_name=attr_name, attr_type=attr_type)
        attribute_definition_list.append(attribute_definition)
    # end for

    template = '''
if(node.op_type == "{op_name}") {{
    {preprocess}
    {attribute_completion_code}
    {postprocess}
    {{
        {attribute_definition}
        {shape_inference_code}
    }}
}}
else
'''
    return template.format(
        op_name=op_name,
        preprocess=preprocess,
        attribute_definition="\n".join(attribute_definition_list),
        shape_inference_code=shape_inference_code,
        postprocess=postprocess,
        attribute_completion_code="\n".join(
            attribute_completion_code_list))


def main():
    template = """
#ifndef MENOH_ATTRIBUTE_COMPLETION_AND_SHAPE_INFERENCE_HPP
#define MENOH_ATTRIBUTE_COMPLETION_AND_SHAPE_INFERENCE_HPP
/*
 * This file is generated by {script_name}
 * Do NOT modify this file directly
 */
#include <algorithm>
#include <cassert>
#include <numeric> // for accumulate
#include <string>
#include <unordered_map>

#include <menoh/array.hpp>
#include <menoh/model_data.hpp>
#include <menoh/utility.hpp>

namespace menoh_impl {{
    inline auto complete_attribute_and_infer_shape(
            model_data& model_data,
            std::unordered_map<std::string, array_profile> const&
                input_profile_table) {{
        using ints = std::vector<int>;
        std::unordered_map<std::string, array_profile> variable_profile_table(
            input_profile_table.begin(), input_profile_table.end());
        std::transform(
            model_data.parameter_name_and_array_list.begin(),
            model_data.parameter_name_and_array_list.end(),
            std::inserter(variable_profile_table,
                          variable_profile_table.end()),
            [](auto const& p){{
                return std::make_pair(
                    p.first,
                    array_profile(p.second.dtype(), p.second.dims())); }});
        auto profile_of = [&variable_profile_table](std::string const& name){{
            if(variable_profile_table.find(name) ==
                variable_profile_table.end()) {{
                throw variable_not_found(name);
            }}
            return variable_profile_table.at(name);
        }};
        auto dims_of = [&variable_profile_table, profile_of](
            std::string const& name){{
                return profile_of(name).dims();
        }};
        auto dtype_of = [&variable_profile_table, profile_of](
            std::string const& name){{
                return profile_of(name).dtype();
        }};
        auto ndims_of = [&dims_of](std::string const& parameter_name) {{
            return dims_of(parameter_name).size();
        }};
        auto add_variable_to_table = [&variable_profile_table](
            std::string const& name,
            dtype_t dtype, ints const& dims){{
                variable_profile_table.emplace(
                    name, array_profile(dtype, dims));
            }};

        auto graph = make_graph(model_data.node_list); // FIXME reorder nodes
        model_data.node_list = graph.node_list();
        for(auto& node : model_data.node_list) {{
            auto input = [&node](auto i){{
                return node.input_name_list.at(i);
            }};
            auto output = [&node](auto i){{
                return node.output_name_list.at(i);
            }};
            {code}
            {unsupported_operator}
        }}
        return variable_profile_table;
    }}
}} // namespace menoh_impl

#endif // MENOH_ATTRIBUTE_COMPLETION_AND_SHAPE_INFERENCE_HPP
"""
    code_list = []
    code_list.append(make_completion_code("Abs"))
    code_list.append(make_completion_code("Add"))
    code_list.append(
        make_completion_code("AveragePool", [
            ("count_include_pad", "int", "0"),
            ("kernel_shape", "ints", None),
            ("pads", "ints", "ints(2*(ndims_of(input(0))-2), 0)"),
            ("strides", "ints", "ints(ndims_of(input(0))-2, 1)"),  # WORKAROUND: None is correct # NOQA
        ], '''
add_variable_to_table(output(0), dtype_of(input(0)),
    calc_2d_output_dims(
        dims_of(input(0)), dims_of(input(0)).at(1),
        kernel_shape, strides, pads));
''', preprocess='''
assert(2 <= ndims_of(input(0)));
'''))
    code_list.append(
        make_completion_code("BatchNormalization", [
            ("epsilon", "float", "1.e-05f"),
            ("momentum", "float", "0.9f"),
            ("spatial", "int", "1"),
        ]))
    code_list.append(
        make_completion_code("Concat", [
            ("axis", "int", None),
        ], '''
auto output_dims = dims_of(input(0));
for(unsigned int i = 1; i < node.input_name_list.size(); ++i) {
    // TODO dim check
    output_dims.at(axis) += dims_of(input(i)).at(axis);
}
add_variable_to_table(output(0), dtype_of(input(0)), output_dims);
'''))
    code_list.append(
        make_completion_code(
            "Conv", [
                ("dilations", "ints", "ints(kernel_ndims, 1)"),
                ("group", "int", "1"),
                ("kernel_shape", "ints", "kernel_shape"),
                ("pads", "ints", "ints(kernel_ndims*2, 0)"),
                ("strides", "ints", "ints(kernel_ndims, 1)"),
            ], '''
add_variable_to_table(output(0), dtype_of(input(0)),
    calc_2d_output_dims(
        dims_of(input(0)), dims_of(input(1)).at(0),
        kernel_shape, strides, pads));
''',
            preprocess='''
auto kernel_ndims = ndims_of(input(1))-2;
auto weights_shape = dims_of(input(1));
auto kernel_shape = ints(weights_shape.begin()+2, weights_shape.end());
'''))
    code_list.append(
        make_completion_code(
            "ConvTranspose",
            [
                ("dilations", "ints", None),
                ("group", "int", "1"),
                ("kernel_shape", "ints", "kernel_shape"),
                ("output_padding", "ints", None),
                # ("output_shape", "ints", None),
                # ("pads", "ints", None),
                ("strides", "ints", "ints(kernel_ndims, 1)"),
            ], '''
add_variable_to_table(output(0), dtype_of(input(0)),
    calc_2d_output_dims_for_conv_transpose(
        dims_of(input(0)), dims_of(input(1)).at(0),
        kernel_shape, strides, get<ints>(node.attribute_table.at("pads"))));
''',
            preprocess='''
auto kernel_ndims = ndims_of(input(1))-2;
auto weights_shape = dims_of(input(1));
auto kernel_shape = ints(weights_shape.begin()+2, weights_shape.end());
''',
            postprocess='''
{
    auto found = node.attribute_table.find("output_shape");
    assert(!(found == node.attribute_table.end() &&
       node.attribute_table.find("pads") == node.attribute_table.end()));
    if(found != node.attribute_table.end()) {
        auto output_shape = get<ints>(found->second);
        /* [dim0_begin, dim1_begin, ... , dim0_end, dim1_end, ..., ...] */
        ints pads(kernel_ndims*2, 0);
        auto output_padding =
            get<ints>(node.attribute_table.at("output_padding"));
        auto strides = get<ints>(node.attribute_table.at("strides"));
        auto input_profile = input_profile_table.at(input(0));
        ints input_size(input_profile.dims().begin()+2,
                        input_profile.dims().end());

        for(unsigned int i = 0; i < kernel_ndims; ++i) {
            auto total_padding = strides[i] * (input_size[i] - 1)
                + output_padding[i] + kernel_shape[i] - output_shape[i];
            pads[i] = total_padding - (total_padding/2);
            pads[i+kernel_ndims] = (total_padding/2);
        }

        node.attribute_table["pads"] = pads;
    }
}
'''))
    code_list.append(make_completion_code("Elu", [("alpha", "float", "1.f")]))
    code_list.append(
        make_completion_code("FC", [], '''
auto output_dims = ints({dims_of(input(0)).at(0), dims_of(input(1)).at(0)});
add_variable_to_table(output(0), dtype_of(input(0)),
    output_dims);
'''))
    code_list.append(
        make_completion_code("Gemm", [
            ("alpha", "float", "1.f"),
            ("beta", "float", "1.f"),
            ("transA", "int", "0"),
            ("transB", "int", "0"),
        ], '''
auto a_dims = dims_of(input(0));
if(ndims_of(input(0)) != 2) {
    int feature_size = std::accumulate(
        a_dims.begin()+1, a_dims.end(), 1, std::multiplies<int>());
    a_dims = ints({a_dims.at(0), feature_size});
}
assert(a_dims.size() == 2);
if(transA) {
    std::swap(a_dims.at(0), a_dims.at(1));
}

auto b_dims = dims_of(input(1));
assert(b_dims.size() == 2);
if(transB) {
    std::swap(b_dims.at(0), b_dims.at(1));
}

if(a_dims.at(1) != b_dims.at(0)) {
    throw dimension_mismatch(
        node.op_type, input(0), "trans(A)[1] and trans(B)[0])",
        std::to_string(a_dims.at(1)), std::to_string(b_dims.at(0)));
}

auto output_dims = ints({a_dims.at(0), b_dims.at(1)});
add_variable_to_table(output(0), dtype_of(input(0)), output_dims);
'''))
    code_list.append(
        make_completion_code("GlobalAveragePool", [], '''
auto input_dims = dims_of(input(0));
auto output_dims = ints({input_dims[0], input_dims[1], 1, 1});
add_variable_to_table(output(0), dtype_of(input(0)),
    output_dims);
'''))
    code_list.append(
        make_completion_code("GlobalMaxPool", [], '''
auto input_dims = dims_of(input(0));
auto output_dims = ints({input_dims[0], input_dims[1], 1, 1});
add_variable_to_table(output(0), dtype_of(input(0)),
    output_dims);
'''))
    code_list.append(
        make_completion_code("LeakyRelu", [("alpha", "float", "0.01f")]))
    code_list.append(
        make_completion_code("LRN", [
            ("alpha", "float", "0.0001f"),
            ("beta", "float", "0.75f"),
            ("bias", "float", "1.0f"),
            ("size", "float", None),
        ]))
    code_list.append(
        make_completion_code("MaxPool", [
            ("kernel_shape", "ints", None),
            ("pads", "ints", "ints(2*(ndims_of(input(0))-2), 0)"),
            ("storage_order", "int", "0"),
            ("strides", "ints", "ints(ndims_of(input(0))-2, 1)"), # WORKAROUND: None is correct # NOQA
        ], '''
add_variable_to_table(output(0), dtype_of(input(0)),
    calc_2d_output_dims(
        dims_of(input(0)), dims_of(input(0)).at(1),
        kernel_shape, strides, pads));
'''))
    code_list.append(make_completion_code("Relu"))
    code_list.append(make_completion_code("Sigmoid"))
    code_list.append(make_completion_code("Softmax", [("axis", "int", "1")]))
    code_list.append(make_completion_code("Sum"))
    code_list.append(make_completion_code("Sqrt"))
    code_list.append(make_completion_code("Tanh"))
    code_list.append(
        make_completion_code("Transpose", [
            ("perm", "ints", "perm"),
        ], '''
auto input_dims = dims_of(input(0));
ints output_dims(input_dims.size());
for(unsigned int i = 0; i < input_dims.size(); ++i) {
    output_dims.at(i) = input_dims.at(perm.at(i));
}
add_variable_to_table(output(0), dtype_of(input(0)), output_dims);
''', preprocess="""
ints perm(ndims_of(input(0)));
for(unsigned int i = 0; i < perm.size(); ++i) {{
    perm.at(i) = perm.size()-i-1;
}}
"""))
    print(template.format(script_name=os.path.basename(__file__), code="\n".join(code_list), unsupported_operator='''
{
    throw unsupported_operator(node.op_type);
}
'''))


if __name__ == "__main__":
    main()
