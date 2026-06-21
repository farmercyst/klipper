// Software serial support for STM32C0 PA12/PA11
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "autoconf.h" // CONFIG_SERIAL_BAUD
#include "board/armcm_boot.h" // armcm_enable_irq
#include "board/irq.h" // irq_save
#include "board/misc.h" // timer_read_time
#include "board/serial_irq.h" // serial_rx_byte
#include "command.h" // DECL_CONSTANT_STR
#include "compiler.h" // DIV_ROUND_CLOSEST
#include "internal.h" // GPIO
#include "sched.h" // DECL_INIT

DECL_CONSTANT_STR("RESERVE_PINS_serial", "PA12,PA11");

#define GPIO_Rx GPIO('A', 12)
#define GPIO_Tx GPIO('A', 11)
#define RX_BIT GPIO2BIT(GPIO_Rx)
#define TX_BIT GPIO2BIT(GPIO_Tx)
#define RX_LINE_IRQ EXTI4_15_IRQn

static uint32_t bit_ticks;

static struct timer rx_timer, tx_timer;
static uint8_t rx_active, rx_bit, rx_byte;
static uint8_t tx_active, tx_bits;
static uint16_t tx_frame;

static inline uint8_t
rx_read(void)
{
    return !!(GPIOA->IDR & RX_BIT);
}

static inline void
tx_write(uint8_t val)
{
    if (val)
        GPIOA->BSRR = TX_BIT;
    else
        GPIOA->BSRR = TX_BIT << 16;
}

static uint_fast8_t
rx_event(struct timer *t)
{
    if (rx_bit < 8) {
        if (rx_read())
            rx_byte |= 1 << rx_bit;
        rx_bit++;
        t->waketime += bit_ticks;
        return SF_RESCHEDULE;
    }

    if (rx_read())
        serial_rx_byte(rx_byte);
    rx_active = 0;
    EXTI->FPR1 = RX_BIT;
    return SF_DONE;
}

void
EXTI4_15_IRQHandler(void)
{
    if (!(EXTI->FPR1 & RX_BIT))
        return;
    EXTI->FPR1 = RX_BIT;
    if (rx_active || rx_read())
        return;

    rx_active = 1;
    rx_bit = 0;
    rx_byte = 0;
    rx_timer.waketime = timer_read_time() + bit_ticks + bit_ticks / 2;
    sched_add_timer(&rx_timer);
}

static void
tx_load_byte(uint8_t data)
{
    tx_write(0);
    tx_frame = data | (1 << 8);
    tx_bits = 9;
}

static void
tx_start_byte(uint8_t data, uint32_t now)
{
    tx_load_byte(data);
    tx_timer.waketime = now + bit_ticks;
    sched_add_timer(&tx_timer);
}

static uint_fast8_t
tx_event(struct timer *t)
{
    if (tx_bits) {
        tx_write(tx_frame & 1);
        tx_frame >>= 1;
        tx_bits--;
        t->waketime += bit_ticks;
        return SF_RESCHEDULE;
    }

    uint8_t data;
    if (serial_get_tx_byte(&data)) {
        tx_active = 0;
        tx_write(1);
        return SF_DONE;
    }
    tx_load_byte(data);
    t->waketime += bit_ticks;
    return SF_RESCHEDULE;
}

void
serial_enable_tx_irq(void)
{
    irqstatus_t flag = irq_save();
    if (!tx_active) {
        uint8_t data;
        if (!serial_get_tx_byte(&data)) {
            tx_active = 1;
            tx_start_byte(data, timer_read_time());
        }
    }
    irq_restore(flag);
}

void
serial_init(void)
{
    bit_ticks = DIV_ROUND_CLOSEST(CONFIG_CLOCK_FREQ, CONFIG_SERIAL_BAUD);

    gpio_peripheral(GPIO_Rx, GPIO_INPUT, 1);
    gpio_peripheral(GPIO_Tx, GPIO_OUTPUT, 0);
    tx_write(1);

    rx_timer.func = rx_event;
    tx_timer.func = tx_event;

    EXTI->EXTICR[3] &= ~EXTI_EXTICR4_EXTI12;
    EXTI->RTSR1 &= ~RX_BIT;
    EXTI->FTSR1 |= RX_BIT;
    EXTI->FPR1 = RX_BIT;
    EXTI->IMR1 |= RX_BIT;
    armcm_enable_irq(EXTI4_15_IRQHandler, RX_LINE_IRQ, 0);
}
DECL_INIT(serial_init);
