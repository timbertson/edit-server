test: edit-server-local.xml
	0install run --command=test edit-server-local.xml

0:
	mkzero-gfxmonk -p edit-server -p xdg -p edit_server edit-server.xml

edit-server-local.xml: edit-server.xml
	0local edit-server.xml


.PHONY: 0
