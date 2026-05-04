# Image Processing Pipeline Timeline

## Processing Stages for Image Pair Extraction

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: DATA INPUT                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Read ROS bag file messages                                                │
│ • Deserialize EventPacket and Image messages                                │
│ • Extract timestamps (header_ns and bag_ts_ns)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: EVENT WINDOW DETERMINATION                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ • For each Basler frame at time basler_ns:                                  │
│   - window_start = basler_ns - window_ms                                    │
│   - window_end = basler_ns + window_ms                                      │
│ • Collect all events within this time window                                │
│ • Check for empty windows and leading drops                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: BASLER IMAGE EXTRACTION & CONVERSION                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Function: image_msg_to_cv2()                                                │
│ • Extract raw bytes from ROS Image message                                  │
│ • Decode based on encoding (mono8, rgb8, bgr8, rgba8, etc.)                 │
│ • Convert to OpenCV numpy array (shape: height × width × channels)          │
│ • Create backup copy → basler_img_raw (saved as-is)                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: BASLER MIRRORING (Optional)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Configuration: mirror_basler_image (boolean)                                │
│ • cv2.flip(basler_img, 1) — horizontal flip if enabled                      │
│ • Applied BEFORE offset/cropping                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
        ╔═══════════════════════════════════════════════════════════╗
        ║          ⭐ PIXEL OFFSET APPLIED HERE ⭐               ║
        ╠═══════════════════════════════════════════════════════════╣
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: BASLER IMAGE CROPPING WITH PIXEL OFFSET                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ Configuration: crop_basler_image (boolean), must also have:                 │
│   • basler_crop_offset_x_px (int) — horizontal offset in pixels             │
│   • basler_crop_offset_y_px (int) — vertical offset in pixels               │
│   • basler_pixel_pitch_um (float) — physical pixel size                     │
│   • event_pixel_pitch_um (float) — physical pixel size                      │
│                                                                             │
│ Function: crop_image_with_offset()                                          │
│ • Calculate crop dimensions based on pixel pitch ratio                      │
│ • Compute crop center:                                                      │
│     center_x = (image_width / 2.0) + offset_x_px                            │
│     center_y = (image_height / 2.0) + offset_y_px                           │
│ • Extract crop window around center                                         │
│ • Clamp to valid image boundaries                                           │
│ • Result: cropped image with offset applied                                 │
│                                                                             │
│ Offset Direction (positive values):                                         │
│   • +offset_x_px → shifts crop RIGHT (positive x direction)                 │
│   • +offset_y_px → shifts crop DOWN (positive y direction)                  │
│                                                                             │
│ Current Config (from default.yaml):                                         │
│   • basler_crop_offset_x_px: 0                                              │
│   • basler_crop_offset_y_px: 0                                              │
└─────────────────────────────────────────────────────────────────────────────┘
        ╚═══════════════════════════════════════════════════════════╝
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: BASLER IMAGE RESIZING                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Check if cropped image dimensions match event resolution                  │
│ • If not, resize using cv2.INTER_LINEAR interpolation                       │
│ • Target resolution: event_resolution (width × height)                      │
│ • Current Config:                                                           │
│     event_resolution.width: 1280                                            │
│     event_resolution.height: 720                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: EVENT IMAGE RENDERING                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ Function: render_event_image()                                              │
│ • Create blank image (height × width × channels)                            │
│ • Plot event coordinates (x, y) with polarity (p):                          │
│   - Polarity 1 (ON event) → RGB(0, 255, 0) [green] or red                   │
│   - Polarity 0 (OFF event) → RGB(0, 0, 255) [blue] or blue                  │
│ • Current color_mode: blue-red                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 8: EVENT IMAGE MIRRORING (Optional)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Configuration: mirror_event_image (boolean)                                 │
│ • cv2.flip(event_img, 1) — horizontal flip if enabled                       │
│ • Applied AFTER rendering                                                   │
│ • Current Config: mirror_event_image = true                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 9: PAIR SYNCHRONIZATION & METADATA                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Compute reference timestamp = median(event_timestamps)                    │
│ • Calculate time delta: delta_us = (ref_ns - basler_ns) / 1000              │
│ • Generate pair ID and filenames                                            │
│ • Log pair metadata (ID, timestamps, event count, window range)             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 10: IMAGE SAVING                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Three files per pair:                                                       │
│                                                                             │
│ 1. basler_raw → Original Basler image (NO offset, NO mirroring)              │
│    Location: basler_raw/                                                    │
│    Filename: pair_XXXXXX_TIMESTAMP_basler_raw.png                           │
│                                                                             │
│ 2. basler → Processed Basler image (WITH offset & mirroring)                 │
│    Location: basler/                                                        │
│    Filename: pair_XXXXXX_TIMESTAMP_basler.png                               │
│    Processing: Mirror (optional) → Crop with OFFSET → Resize                │
│                                                                             │
│ 3. event → Rendered event image (with event image mirroring)                │
│    Location: event/                                                         │
│    Filename: pair_XXXXXX_TIMESTAMP_event.png                                │
│                                                                             │
│ • CSV metadata (pairs.csv):                                                 │
│   pair_id, basler_ns, ref_ns, delta_us, event_count,                        │
│   window_start_ns, window_end_ns, basler_path, event_path                   │
│                                                                             │
│ • HDF5 raw events (if raw_events_hdf5 = true)                               │
│   Events: timestamps, x, y, polarity                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Insights on Pixel Offset

### When Offset is Applied
- **Stage 5** during the **crop_image_with_offset()** function call
- Offset acts as a **center shift** for the crop window
- Applied **before resizing** to event resolution

### How It Works
```python
# Current implementation
center_x = (image_width / 2.0) + offset_x_px    # Offset shifts center horizontally
center_y = (image_height / 2.0) + offset_y_px   # Offset shifts center vertically

# Then crop window is extracted around this shifted center
left = center_x - (crop_width / 2.0)
top = center_y - (crop_height / 2.0)
```

### Current Configuration
In your `config/profiles/default.yaml`:
- `basler_crop_offset_x_px: 0` → No horizontal shift
- `basler_crop_offset_y_px: 0` → No vertical shift

### Coordinate System
- **Positive X offset**: Shifts crop **RIGHT** (increases center_x)
- **Positive Y offset**: Shifts crop **DOWN** (increases center_y)
- Origin (0,0) is at **top-left** of the image

### Order of Operations (Important!)
1. ✅ Raw image conversion
2. ✅ Mirror (if enabled) — **applied first**
3. ✅ **Pixel offset applied during crop** — **applied second**
4. ✅ Resize — **applied after offset**

This means if you have mirror enabled, the offset is computed on the **mirrored** image, not the original!

## Related Configuration Parameters
- `basler_pixel_pitch_um`: 4.8 μm (physical pixel size on Basler)
- `event_pixel_pitch_um`: 4.86 μm (physical pixel size on event camera)
- `crop_basler_image`: Whether cropping is enabled at all
- `mirror_basler_image`: Whether to flip horizontally before cropping

## Output Comparison
- **basler_raw**: Shows what the camera actually captured (no processing)
- **basler**: Shows the aligned output (with your offset applied)
- **event**: The event camera rendering for the same time window
