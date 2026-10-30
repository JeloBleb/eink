#![no_std]
#![no_main]

use esp_backtrace as _;
use esp_hal::delay::Delay;
use esp_hal::spi::master::{Config as SpiConfig, Spi};
use esp_hal::time::Rate;
use esp_hal::{Blocking, gpio::*};
use esp_println::println;

esp_bootloader_esp_idf::esp_app_desc!();

static IMAGE: &[u8] = include_bytes!("../photo.bin");

struct Epd<'d> {
    rst: Output<'d>,
    dc: Output<'d>,
    cs: Output<'d>,
    busy: Input<'d>,
    spi: Spi<'d, Blocking>,
    delay: Delay,
}

impl Epd<'_> {
    fn send_command(&mut self, command: u8) {
        let Epd { dc, cs, spi, .. } = self;

        dc.set_low();
        cs.set_low();
        spi.write(&[command]).unwrap();
        cs.set_high();
    }

    fn send_data(&mut self, data: &[u8]) {
        let Epd { dc, cs, spi, .. } = self;

        dc.set_high();
        cs.set_low();
        spi.write(data).unwrap();
        cs.set_high();
    }

    fn wait_busy(&self) {
        let mut ms = 0u32;
        while self.busy.is_low() {
            self.delay.delay_millis(1);
            ms += 1;
        }
        println!("was busy for {ms} milliseconds");
    }

    fn reset(&mut self) {
        self.rst.set_low();
        self.delay.delay_millis(10);
        self.rst.set_high();
        self.delay.delay_millis(40);
        self.wait_busy();
    }

    fn power_on(&mut self) {
        self.send_command(0x04);
        self.wait_busy();
    }

    fn power_off(&mut self) {
        self.send_command(0x02);
        self.send_data(&[0x00]);
        self.wait_busy();
    }

    fn sleep(&mut self) {
        self.send_command(0x07);
        self.send_data(&[0xA5]);
    }

    fn init(&mut self) {
        self.send_command(0x00);
        self.send_data(&[0x2B, 0x29]);
        self.send_command(0x06);
        self.send_data(&[0x0F, 0x8B, 0x93, 0xC1]);
        self.send_command(0x50);
        self.send_data(&[0x37]);
        self.send_command(0x30);
        self.send_data(&[0x08]);
        self.send_command(0x61);
        self.send_data(&[0x03, 0x20, 0x02, 0xA8]);
        self.send_command(0x62);
        self.send_data(&[0x76, 0x76, 0x76, 0x5A, 0x9D, 0x8A, 0x76, 0x62]);
        self.send_command(0x65);
        self.send_data(&[0x00, 0x00, 0x00, 0x00]);
        self.send_command(0xE0);
        self.send_data(&[0x10]);
        self.send_command(0xE7);
        self.send_data(&[0xA4]);
        self.send_command(0xE9);
        self.send_data(&[0x01]);
    }

    fn send_solid_color(&mut self, color: Color) {
        let row = [color as u8 * 0b01_01_01_01; 200];
        self.send_command(0x10);
        (0..680).for_each(|_| {
            self.send_data(&row);
        });
    }

    fn send_image(&mut self) {
        self.send_command(0x10);
        self.send_data(IMAGE);
    }

    fn refresh(&mut self) {
        self.send_command(0x12);
        self.send_data(&[0x00]);
    }
}

enum Color {
    Black = 0b00,
    White = 0b01,
    Yellow = 0b10,
    Red = 0b11,
}

#[esp_hal::main]
fn main() -> ! {
    let peripherals = esp_hal::init(esp_hal::Config::default());
    let delay = Delay::new();

    //Creating pin drivers
    let rst = Output::new(peripherals.GPIO40, Level::Low, OutputConfig::default());
    let cs = Output::new(peripherals.GPIO42, Level::High, OutputConfig::default());
    let dc = Output::new(peripherals.GPIO41, Level::Low, OutputConfig::default());
    let busy = Input::new(
        peripherals.GPIO39,
        InputConfig::default().with_pull(Pull::Up),
    );

    let spi = Spi::new(
        peripherals.SPI2,
        SpiConfig::default()
            .with_frequency(Rate::from_mhz(10))
            .with_mode(esp_hal::spi::Mode::_0),
    )
    .unwrap()
    .with_sck(peripherals.GPIO2)
    .with_mosi(peripherals.GPIO1);

    let mut epd = Epd {
        rst,
        dc,
        cs,
        busy,
        spi,
        delay,
    };

    epd.reset();
    epd.init();
    println!("powering on");
    epd.power_on();
    println!("powered on");
    epd.send_solid_color(Color::White);
    epd.send_image();
    println!("sending image");
    epd.refresh();
    println!("panel refreshing");
    epd.power_off();
    println!("powered off");
    epd.sleep();
    println!("epd going to sleep");

    loop {
        delay.delay_millis(10000);
        println!("board is still running");
    }
}
