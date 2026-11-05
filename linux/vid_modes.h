#ifndef LINUX_VID_MODES_H
#define LINUX_VID_MODES_H

typedef struct {
	const char *label;
	int width;
	int height;
} linux_vid_mode_t;

static const linux_vid_mode_t linux_vid_modes[] = {
	{ "320x240",   320,  240 }, // Modo 0
	{ "400x300",   400,  300 }, // Modo 1
	{ "512x384",   512,  384 }, // Modo 2
	{ "640x480",   640,  480 }, // Modo 3
	{ "800x600",   800,  600 }, // Modo 4
	{ "960x720",   960,  720 }, // Modo 5
	{ "1024x768", 1024,  768 }, // Modo 6
	{ "1152x864", 1152,  864 }, // Modo 7
	{ "1280x720", 1280,  720 }, // HD 720p
	{ "1280x960", 1280,  960 }, // Padrão clássico Quake 2
	{ "1366x768", 1366,  768 }, // HD Notebook
	{ "1600x1200",1600, 1200 }, // UXGA
	{ "1920x1080",1920, 1080 }
};

#define LINUX_VID_MODE_COUNT \
    (sizeof(linux_vid_modes) / sizeof(linux_vid_modes[0]))

#endif