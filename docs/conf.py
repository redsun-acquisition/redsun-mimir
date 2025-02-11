# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'redsun-mimir'
copyright = "2025, Jacopo Abramo"
author = 'Jacopo Abramo'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx_design',
    'myst_parser'
]

templates_path = ['_templates']
exclude_patterns = ['_build']

myst_enable_extensions = ['attrs_block', 'colon_fence']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'pydata_sphinx_theme'
html_static_path = ['_static']
html_context = {
    # set theme color
    # depending on local system
    # configuration
   "default_mode": "auto"
}

source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

napoleon_numpy_docstring = True
autodoc_typehints = 'description'

myst_heading_anchors = 3
