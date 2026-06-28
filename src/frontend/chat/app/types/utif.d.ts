// utif (UTIF.js) không ship type declarations — khai báo tối thiểu phần ta dùng.
declare module 'utif' {
  interface IFD {
    width: number
    height: number
    [key: string]: unknown
  }
  export function decode(buffer: ArrayBuffer | Uint8Array): IFD[]
  export function decodeImage(buffer: ArrayBuffer | Uint8Array, ifd: IFD): void
  export function toRGBA8(ifd: IFD): Uint8Array
  const _default: {
    decode: typeof decode
    decodeImage: typeof decodeImage
    toRGBA8: typeof toRGBA8
  }
  export default _default
}
