#pragma once
#include <Arduino.h>
#include <esp_err.h>
using i2s_port_t=int; using i2s_mode_t=int; using i2s_channel_fmt_t=int;
constexpr int I2S_NUM_0=0,I2S_NUM_1=1,I2S_MODE_MASTER=1,I2S_MODE_RX=2,I2S_MODE_PDM=4,I2S_MODE_TX=8;
constexpr int I2S_CHANNEL_FMT_ONLY_LEFT=1,I2S_CHANNEL_FMT_RIGHT_LEFT=2,I2S_BITS_PER_SAMPLE_16BIT=16;
constexpr int I2S_COMM_FORMAT_STAND_I2S=0,ESP_INTR_FLAG_LEVEL1=1,I2S_MCLK_MULTIPLE_DEFAULT=0,I2S_BITS_PER_CHAN_DEFAULT=0,I2S_PIN_NO_CHANGE=-1;
struct i2s_config_t { int mode,sample_rate,bits_per_sample,channel_format,communication_format,intr_alloc_flags,dma_buf_count,dma_buf_len; bool use_apll,tx_desc_auto_clear; int fixed_mclk,mclk_multiple,bits_per_chan; };
struct i2s_pin_config_t { int mck_io_num,bck_io_num,ws_io_num,data_out_num,data_in_num; };
inline size_t mock_write_limit=SIZE_MAX;
inline int mock_dma_clears=0,mock_amp_stops=0;
inline std::vector<int16_t> mock_written;
inline int i2s_driver_install(int,const i2s_config_t*,int,void*) {return ESP_OK;}
inline int i2s_set_pin(int,const i2s_pin_config_t*) {return ESP_OK;}
inline int i2s_start(int) {return ESP_OK;}
inline int i2s_stop(int port) {if(port==1)++mock_amp_stops;return ESP_OK;}
inline int i2s_zero_dma_buffer(int port) {if(port==1)++mock_dma_clears;return ESP_OK;}
inline int i2s_read(int,void*,size_t,size_t* n,int) {*n=0;return ESP_OK;}
inline int i2s_write(int,const void* data,size_t n,size_t* written,int) {
  *written=std::min(n,mock_write_limit);const auto* pcm=static_cast<const int16_t*>(data);
  mock_written.insert(mock_written.end(),pcm,pcm+*written/2);
  return *written<n?ESP_ERR_TIMEOUT:ESP_OK;
}
