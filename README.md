<img src="http://gfxmonk.net/dist/status/project/edit-server.png">

An edit server written in python, compatible with TextAid and other similar
google chrome extensions. The purpose of which is to edit a browser's
textarea in an external text editor (like vim, emacs, etc...)

Runs on port 9292, or whatever port you pass in (see --help)
Listens on the local interface only.
Editor command is defaulted to `gvim -f`, but will use ARGV instead
if you give it any (non-optional) arguments.

# Incremental file editing:

Supports incremental editing, which requires a version of the chrome plugin
released after 2010-10-24. If you find your textareas never update after the
first time you save the file in your editor, your version is too old. You can
use --no-incremental to revert to the old behaviour.

### Tech details

The incremental editing uses two HTTP headers, "x-file" and "x-open".
"x-open: true" means the editor has not finished, and another request should be made
immediately. "x-file: FILENAME" (returned from the server) provides the value to be
provided as the "x-file" request header for the subsequent request.
if "x-file" is not "true", the editing has finished and no more requests should be
made.
