# noqa: D100
#!/usr/bin/env python
#
# xscen documentation build configuration file, created by
# sphinx-quickstart on Fri Jun  9 13:47:02 2017.
#
# This file is execfile()d with the current directory set to its
# containing dir.
#
# Note that not all possible configuration values are present in this
# autogenerated file.
#
# All configuration values have a default; values that are commented out
# serve to show the default.

# If extensions (or modules to document with autodoc) are in another
# directory, add these directories to sys.path here. If the directory is
# relative to the documentation root, use os.path.abspath to make it
# absolute, like shown here.
#
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(".."))
if os.environ.get("READTHEDOCS") and "ESMFMKFILE" not in os.environ:
    # RTD doesn't activate the env, and esmpy depends on a env var set there
    # We assume the `os` package is in {ENV}/lib/pythonX.X/os.py
    # See conda-forge/esmf-feedstock#91 and readthedocs/readthedocs.org#4067
    os.environ["ESMFMKFILE"] = str(Path(os.__file__).parent.parent / "esmf.mk")

import xscen  # noqa
import xarray  # noqa

xarray.DataArray.__module__ = "xarray"
xarray.Dataset.__module__ = "xarray"

# -- General configuration ---------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.autosummary",
    "sphinx.ext.coverage",
    "sphinx.ext.extlinks",
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "nbsphinx",
    "sphinx_codeautolink",
    "sphinx_copybutton",
]

# To ensure that underlined fields (e.g. `_field`) are shown in the docs.
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "private-members": False,
    "special-members": False,
}

autosectionlabel_prefix_document = True
autosectionlabel_maxdepth = 2

autosummary_generate = True

nbsphinx_execute = "always"
# To avoid running notebooks on linkcheck and when building PDF.
try:
    skip_notebooks = int(os.getenv("SKIP_NOTEBOOKS"))
except TypeError:
    skip_notebooks = False
if skip_notebooks:
    warnings.warn("SKIP_NOTEBOOKS is set. Not executing notebooks.")
    nbsphinx_execute = "never"
elif (os.getenv("READTHEDOCS_VERSION_NAME") in ["latest", "stable"]) or (
    os.getenv("READTHEDOCS_VERSION_TYPE") in ["tag"]
):
    if Path(__file__).parent.joinpath("notebooks/_data").exists():
        warnings.warn("Notebook artefacts found. Not executing notebooks.")
        nbsphinx_execute = "never"

# if skip_notebooks or os.getenv("READTHEDOCS_VERSION_TYPE") in [
#     "branch",
#     "external",
# ]:
#     warnings.warn("Not executing notebooks.")
#     nbsphinx_execute = "never"

# To avoid having to install these and burst memory limit on ReadTheDocs.
# autodoc_mock_imports = [
#     "cartopy",
#     "clisops",
#     "dask",
#     "h5py",
#     "intake",
#     "intake_esm",
#     "pandas",
#     "rechunker"
#     "xarray",
#     "xclim",
#     "xesmf",
#     "zarr",
# ]

napoleon_numpy_docstring = True
napoleon_use_rtype = False
napoleon_use_param = False
napoleon_use_ivar = True

intersphinx_mapping = {
    "xclim": ("https://xclim.readthedocs.io/en/latest/", None),
    "xarray": ("https://docs.xarray.dev/en/stable/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "intake-esm": ("https://intake-esm.readthedocs.io/en/stable/", None),
    "clisops": ("https://clisops.readthedocs.io/en/latest/", None),
    "rechunker": ("https://rechunker.readthedocs.io/en/latest/", None),
    "xesmf": ("https://pangeo-xesmf.readthedocs.io/en/latest/", None),
}

extlinks = {
    "issue": ("https://github.com/Ouranosinc/xscen/issues/%s", "GH/%s"),
    "pull": ("https://github.com/Ouranosinc/xscen/pull/%s", "PR/%s"),
    "user": ("https://github.com/%s", "@%s"),
}

linkcheck_ignore = [
    r"https://github.com/Ouranosinc/xscen/(pull|issue).*",  # too labourious to fully check
    r"https://rmets.onlinelibrary.wiley.com/doi/10.1002/qj.3803",  # Error 403: Forbidden
    r"https://library.wmo.int/idurl/4/56300",  # HTTPconnectionPool error
]

# Add any paths that contain templates here, relative to this directory.
# templates_path = ['_templates']

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = [".rst"]

# The master toctree document.
master_doc = "index"

# General information about the project.
project = "xscen"
copyright = f"2022-{datetime.now().year}, Ouranos Inc., Gabriel Rondeau-Genesse, and contributors"
author = "Gabriel Rondeau-Genesse"

# The version info for the project you're documenting, acts as replacement
# for |version| and |release|, also used in various other places throughout
# the built documents.
#
# The short X.Y version.
version = xscen.__version__
# The full version, including alpha/beta/rc tags.
release = xscen.__version__

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = "en"

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This patterns also effect to html_static_path and html_extra_path
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"

# If true, `todo` and `todoList` produce output, else they produce nothing.
todo_include_todos = False


# -- Options for HTML output -------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_title = "Ouranos xscen Official Documentation"
html_short_title = "xscen"

html_theme = "sphinx_rtd_theme"

# Theme options are theme-specific and customize the look and feel of a
# theme further.  For a list of options available for each theme, see the
# documentation.
#
html_theme_options = {"logo_only": True, "style_external_links": True}

# The name of an image file (relative to this directory) to place at the top
# of the sidebar.
html_logo = "_static/_images/xscen-logo.png"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]


# -- Options for HTMLHelp output ---------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = "xscendoc"


# -- Options for LaTeX output ------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',
    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',
    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',
    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto, manual, or own class]).
latex_documents = [
    (
        master_doc,
        "xscen.tex",
        "xscen Documentation",
        "Gabriel Rondeau-Genesse",
        "manual",
    ),
]


# -- Options for manual page output ------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [(master_doc, "xscen", "xscen Documentation", [author], 1)]


# -- Options for Texinfo output ----------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (
        master_doc,
        "xscen",
        "xscen Documentation",
        author,
        "xscen",
        "One line description of project.",
        "Miscellaneous",
    ),
]
